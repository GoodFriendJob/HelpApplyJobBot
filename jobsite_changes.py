import re
import yaml
import os
from typing import Dict, List, Optional
from datetime import datetime


def saveUnansweredQuestion(self, question: str, options: Optional[List[str]] = None, section: str = "inputField") -> None:
    question = self.cleanQuestion(question)
    if not question:
        return

    pending_path = "pendingQuestions.yaml"
    try:
        if os.path.exists(pending_path):
            with open(pending_path, "r", encoding="utf-8") as f:
                pending = yaml.safe_load(f) or {}
        else:
            pending = {}

        for key in ["inputField", "radio", "dropdown", "checkbox"]:
            if key not in pending:
                pending[key] = {}

        if section not in pending:
            pending[section] = {}

        option_str = "|".join(options) if options else None
        if question not in pending[section]:
            pending[section][question] = option_str

        with open(pending_path, "w", encoding="utf-8") as f:
            yaml.dump(pending, f, allow_unicode=True, sort_keys=False)
    except Exception:
        pass

    log_path = "data/Manual Answer Questions.csv"
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f'"{question}",1,{now},{self.siteName},"{self.currentCompany}","{self.currentTitle}","","{section}",Unanswered\n'

        if not os.path.exists(log_path):
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8", newline="") as f:
                f.write("Question,Times,Last Seen,Site,Company,Job Title,Link,Section,Status\n")
                f.write(entry)
        else:
            with open(log_path, "a", encoding="utf-8", newline="") as f:
                f.write(entry)
    except Exception:
        pass


def fillInputs(self) -> None:
    self.refreshAnswers()
    scope = self.dialogScope()
    if scope is None:
        return
    fields = scope.find_elements(By.CSS_SELECTOR, "input:not([type='hidden']):not([type='submit']):not([type='checkbox']):not([type='radio']), textarea")

    for field in fields:
        try:
            if not field.is_displayed() or not field.is_enabled() or (field.get_attribute("value") or "").strip():
                continue
            label = self.labelFor(field)
            question = label or self.questionText(field)
            inputType = (field.get_attribute("type") or "").lower()
            if (field.get_attribute("role") or "").lower() == "combobox" or (field.get_attribute("aria-autocomplete") or "").lower() in ("list", "both"):
                continue
            if self.isDateField(field, question):
                self.fillDate(field, question)
                continue
            value = None
            if inputType == "tel" or "phone" in question or "mobile" in question:
                value = self.phoneNumber()
            elif inputType == "email" or "email" in question:
                value = self.email or config.Email
            if not value and re.search(r"if other|please (specify|provide|explain|describe)|other \(please|if yes, (please )?(specify|explain)", question) and len(question) < 80:
                previous = self.previousQuestion(field)
                value = (self.openAnswer(previous) if previous else None) or ("No" if previous and re.search(r"refer|family|relative", previous) else None)
            isTextarea = field.tag_name.lower() == "textarea"
            source = "profile" if value else ""
            if not value:
                value = self.matchAnswer("inputField", question)
                countQuestion = re.search(r"how many|number of", question)
                if value and re.fullmatch(r"[\d.,]+", value.strip()) and not countQuestion and (isTextarea or not re.search(r"year|how much|\brate\b|scale|gpa|hours|days|weeks?\b", question)):
                    value = None
                source = "yaml" if value else ""
            if not value and re.search(r"address line 2|address 2\b|\bapt\b|apartment|suite|unit number|\bsuffix\b", question):
                continue
            if not value:
                manualKey = self.manualEntry(label or question)
                if manualKey:
                    self.flagManual(label or question, manualKey)
                    continue
            if not value:
                value = self.openAnswer(question)
                source = "profile" if value else ""
            if not value and "year" in question and re.search(r"\b(manag\w*|lead\w*|supervis\w*)\b", question):
                value = str(config.yearsLeadingTeams)
                source = "profile"
            if not value:
                if not isTextarea or re.search(r"how many years", question):
                    if inputType == "number" or self.isNumericField(field) or re.search(r"\byears?\b|how many", question):
                        value = str(config.yearsOfExperience)
            if not value and isTextarea:
                self.saveUnansweredQuestion(question, section="inputField")
                continue
            if value and self.isNumericField(field) and not re.fullmatch(r"[\d.,]+", str(value).strip()):
                if "gpa" in question:
                    continue
                value = self.payNumber(question) if re.search(r"salary|pay|rate|compensation|wage", question) else str(config.yearsOfExperience)
            if value:
                self.typeInto(field, str(value))
                if not re.fullmatch(r"[\d.,]+", str(value).strip()) and self.fieldInvalid(field):
                    value = self.payNumber(question) if re.search(r"salary|pay|rate|compensation|wage", question) else str(config.yearsOfExperience)
                    self.typeInto(field, value)
                self.answeredQuestions.append(f"{question[:90]} -> {str(value)[:60]} [{source or 'default'}]")
        except Exception:
            continue


def fillSelects(self) -> None:
    self.refreshAnswers()
    scope = self.dialogScope()
    if scope is None:
        return
    selects = scope.find_elements(By.CSS_SELECTOR, "select")

    for select in selects:
        try:
            if not select.is_displayed() or not select.is_enabled():
                continue
            if (select.get_attribute("value") or "").strip():
                continue
            label = self.labelFor(select)
            question = label or self.questionText(select)
            s = Select(select)
            value = self.matchAnswer("dropdown", question)
            options = [opt.text.strip() for opt in s.options[1:] if opt.text.strip()]
            if not value and options:
                normalized_q = self.normalizeText(question.lower())
                for opt in options:
                    if self.keyMatches(opt, question.lower(), normalized_q):
                        value = opt
                        break
            if not value and options:
                self.saveUnansweredQuestion(question, options, "dropdown")
                continue
            if value:
                try:
                    s.select_by_value(value)
                except Exception:
                    try:
                        s.select_by_visible_text(value)
                    except Exception:
                        for opt in s.options:
                            if opt.text.strip() == value:
                                s.select_option(opt)
                                break
                self.answeredQuestions.append(f"{question[:90]} -> {value[:60]} [yaml]")
        except Exception:
            continue


def fillRadios(self) -> None:
    self.refreshAnswers()
    scope = self.dialogScope()
    if scope is None:
        return
    groups = scope.find_elements(By.CSS_SELECTOR, "[role='radiogroup'], [role='group'], fieldset")

    for group in groups:
        try:
            radios = group.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            if not radios or all(r.get_attribute("checked") for r in radios):
                continue
            question = self.labelFor(radios[0]) or self.questionText(group)
            if not question:
                continue
            value = self.matchAnswer("radio", question)
            options = []
            for radio in radios:
                opt_label = radio.get_attribute("aria-label") or ""
                if not opt_label:
                    label_el = group.find_element(By.CSS_SELECTOR, f"label[for='{radio.get_attribute('id')}']") if radio.get_attribute("id") else None
                    opt_label = (label_el.text if label_el else "").strip()
                if not opt_label:
                    opt_label = self.questionText(radio)
                if opt_label and opt_label.lower() != question.lower():
                    options.append(opt_label)
            if not value and options:
                normalized_q = self.normalizeText(question.lower())
                for opt in options:
                    if self.keyMatches(opt, question.lower(), normalized_q):
                        value = opt
                        break
            if not value and options:
                self.saveUnansweredQuestion(question, options, "radio")
                continue
            if value:
                for radio in radios:
                    if value.lower() in (radio.get_attribute("aria-label") or "").lower() or value.lower() in (radio.get_attribute("value") or "").lower():
                        radio.click()
                        self.answeredQuestions.append(f"{question[:90]} -> {value[:60]} [yaml]")
                        break
        except Exception:
            continue


def fillComboboxes(self) -> None:
    self.refreshAnswers()
    scope = self.dialogScope()
    if scope is None:
        return
    comboboxes = scope.find_elements(By.CSS_SELECTOR, "[role='combobox'], input[aria-autocomplete]")

    for combobox in comboboxes:
        try:
            if not combobox.is_displayed() or not combobox.is_enabled() or (combobox.get_attribute("value") or "").strip():
                continue
            question = self.labelFor(combobox) or self.questionText(combobox)
            normalized_q = self.normalizeText(question.lower())
            q_lower = question.lower()

            value = self.matchAnswer("dropdown", q_lower)
            if not value:
                value = self.matchAnswer("radio", q_lower)
            if not value:
                value = self.matchAnswer("inputField", q_lower)

            if not value:
                self.typeInto(combobox, "")
                self.pause(0.5, 1)
                options = scope.find_elements(By.CSS_SELECTOR, "[role='option']")
                options = [opt.text.strip() for opt in options if opt.text.strip()]

                if options:
                    for opt in options:
                        if self.keyMatches(opt, q_lower, normalized_q):
                            value = opt
                            break

            if not value:
                options = scope.find_elements(By.CSS_SELECTOR, "[role='option']")
                options = [opt.text.strip() for opt in options if opt.text.strip()]
                if options:
                    self.saveUnansweredQuestion(question, options, "dropdown")
                continue

            if value:
                self.typeInto(combobox, value)
                self.pause(0.5, 1)
                self.answeredQuestions.append(f"{question[:90]} -> {value[:60]} [yaml]")
        except Exception:
            continue


def fillChoiceGroups(self) -> None:
    self.refreshAnswers()
    scope = self.dialogScope()
    if scope is None:
        return
    checkboxes = scope.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
    processed_groups = set()

    for checkbox in checkboxes:
        try:
            group = checkbox.find_element(By.XPATH, "ancestor::fieldset | ancestor::div[@role='group'] | ancestor::div[@role='radiogroup']")
            group_id = group.get_attribute("id") or str(group.location)
            if group_id in processed_groups:
                continue
            processed_groups.add(group_id)

            if not group.is_displayed():
                continue

            question = self.labelFor(checkbox) or self.questionText(group)
            value = self.matchAnswer("checkbox", question)

            if not value:
                options = [cb.get_attribute("aria-label") or cb.get_attribute("value") or "" for cb in group.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")]
                options = [o for o in options if o]
                if options:
                    self.saveUnansweredQuestion(question, options, "checkbox")
                continue

            if value:
                values = [v.strip() for v in value.split(",")]
                for cb in group.find_elements(By.CSS_SELECTOR, "input[type='checkbox']"):
                    cb_value = cb.get_attribute("value") or ""
                    cb_label = cb.get_attribute("aria-label") or ""
                    for v in values:
                        if v.lower() in (cb_value.lower(), cb_label.lower()):
                            if not cb.is_selected():
                                cb.click()
                            self.answeredQuestions.append(f"{question[:90]} -> {v[:60]} [yaml]")
        except Exception:
            continue
