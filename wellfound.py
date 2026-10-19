import subprocess
import sys
import time
from typing import List
from urllib.parse import quote_plus

import config
import utils
from jobsite import JobSiteBot

from selenium.webdriver.common.by import By


class Wellfound(JobSiteBot):
    siteName = "Wellfound"
    homeUrl = "https://wellfound.com"
    protectedUrl = "https://wellfound.com/messages"
    loginUrl = "https://wellfound.com/login"
    applyTexts = ["apply", "apply now", "easy apply"]

    def __init__(self) -> None:
        super().__init__(config.wellfoundEmail, config.wellfoundPassword)

    def login(self) -> None:
        self.open(self.loginUrl)
        self.pause(3, 5)
        self.clickText(["sign in with email", "use email instead", "continue with email"])
        self.pause(2, 3)
        emails = [e for e in self.driver.find_elements(By.CSS_SELECTOR, "input[type='email'], input[name='email']") if e.is_displayed()]
        if emails and self.email:
            self.typeInto(emails[0], self.email)
            self.clickText(["continue", "next"], exact=True)
            self.pause(3, 5)
        passwords = [p for p in self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']") if p.is_displayed()]
        if passwords and self.password:
            self.typeInto(passwords[0], self.password)
            self.clickText(["sign in", "log in", "continue"], exact=True)
            self.pause(6, 9)

    def searchUrl(self, keyword: str, location: str, page: int) -> str:
        params = [("query", keyword), ("page", str(page))]
        if (location and location.lower() == "remote") or config.remote == ["Remote"]:
            params.append(("remote", "true"))
        return "https://wellfound.com/jobs?" + "&".join(f"{k}={quote_plus(v)}" for k, v in params)

    def collectJobLinks(self) -> List[str]:
        links = []
        for anchor in self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/jobs/']"):
            href = (anchor.get_attribute("href") or "").split("?")[0]
            if href and "/jobs/" in href and not href.rstrip("/").endswith("/jobs") and href not in links:
                links.append(href)
        return links

    def jobProperties(self) -> List[str]:
        title = ""
        company = ""
        location = ""
        try:
            title = self.driver.find_element(By.CSS_SELECTOR, "h1").text.strip()
        except Exception:
            pass
        for selector in ["a[href*='/company/']", "[data-test='StartupLink']", "h2 a"]:
            try:
                company = self.driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                if company:
                    break
            except Exception:
                continue
        for selector in ["[data-test='job-location']", "[data-test='LocationBadge']"]:
            try:
                location = self.driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                if location:
                    break
            except Exception:
                continue
        return [title, company, location]

    def appliedOnPage(self) -> bool:
        text = self.pageText()
        return any(t in text for t in self.successTexts) or "application sent" in text or "you applied" in text or "you've applied" in text

    def applyToJob(self, url: str) -> None:
        self.open(url)
        self.pause(2, 4)
        self.countJobs += 1
        self.answeredQuestions = []
        title, company, location = self.jobProperties()
        self.currentTitle, self.currentCompany, self.currentLocation = title, company, location
        properties = f"{self.countJobs} | {title} | {company} | {location}"

        reason = self.isBlacklisted(title, company) or self.techBlacklisted(title)
        if reason:
            self.countBlacklisted += 1
            self.record(properties + f" ({reason})", "* 🤬 Blacklisted Job, skipped!", url)
            return

        notRemote = self.notRemoteReason(title, location)
        if notRemote:
            self.countNotRemote += 1
            self.record(properties + f" ({notRemote})", "* 🏢 Not a fully remote job, skipped!", url)
            return

        if self.appliedOnPage():
            self.countAlreadyApplied += 1
            self.record(properties, "* 🥳 Already applied!", url)
            return

        button = self.findClickable(self.applyTexts)
        if button is None:
            self.countCannotApply += 1
            self.record(properties, "* 🥵 No Apply button", url)
            return

        if config.dryRun:
            self.record(properties, "* 🧪 DRY RUN - Would apply to this job", url)
            return

        mainWindow = self.driver.current_window_handle
        knownWindows = list(self.driver.window_handles)
        self.click(button)
        self.pause(2, 3)
        self.switchToNewWindow(knownWindows)

        if self.appliedOnPage():
            result = "applied"
        else:
            result = self.completeApplication()
            for qa in self.answeredQuestions:
                self.displayWriteResults(f"      ❓ {qa}")
            if result != "applied" and self.appliedOnPage():
                result = "applied"

        if result == "applied":
            self.applied()
            self.record(properties, "* 🥳 Just Applied to this job", url)
        else:
            self.countCannotApply += 1
            self.record(properties, "* 🥵 Cannot apply to this Job! (needs manual answers)", url)
        self.closeExtraWindows(mainWindow)

    def searchAndApply(self) -> None:
        for location in config.searchLocations:
            for keyword in config.skills:
                self.displayWriteResults(f"\n Wellfound | Category: {keyword}, Location: {location}")
                for page in range(1, config.maxPagesPerSearch + 1):
                    try:
                        self.open(self.searchUrl(keyword, location, page))
                        self.pause(3, 5)
                        links = [link for link in self.collectJobLinks() if link not in self.seenJobs]
                    except Exception as e:
                        self.displayWriteResults(f"* 🥵 Could not load search page {page}: {str(e)[0:80]}")
                        self.recoverRenderer()
                        continue
                    if not links:
                        break
                    for link in links:
                        self.seenJobs.add(link)
                        self.ensureWindow()
                        try:
                            self.applyToJob(link)
                        except Exception as e:
                            self.countCannotApply += 1
                            self.record(f"{self.countJobs} | {self.currentTitle} | {self.currentCompany}", f"* 🥵 Error: {str(e)[0:80]}", link)
                        if self.reachedCap():
                            return
                utils.prYellow(f"Wellfound | {keyword}, {location}: applied {self.countApplied} of {self.countJobs} jobs so far.")

    def processPendingQuestions(self) -> None:
        try:
            result = subprocess.run([sys.executable, "process_pending_to_yaml.py"], capture_output=True, text=True)
        except Exception as e:
            utils.prRed("❌ Could not run process_pending_to_yaml.py: " + str(e)[:120])
            return
        if result.returncode != 0:
            utils.prRed("❌ process_pending_to_yaml.py failed (exit " + str(result.returncode) + "): " + (result.stderr or "")[:200])
            return
        if result.stdout:
            print(result.stdout.strip())
        self.refreshAnswers()
        utils.prGreen("✅ Pending questions processed into additionalQuestions.yaml")

    def run(self) -> None:
        self.searchAndApply()
        self.processPendingQuestions()


def main() -> None:
    start = time.time()
    Wellfound().start()
    utils.prYellow("---Took: " + str(round((time.time() - start) / 60)) + " minute(s).")


if __name__ == "__main__":
    main()
