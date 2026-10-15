import os
import re
import time
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

import config

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# Parameters a provider may reject; dropped and retried instead of failing the request.
OPTIONAL_PARAMS = ("temperature", "reasoning_effort", "top_p")

SENSITIVE_PATTERN = r"\bssn\b|social security|passport|\bbank\b|routing number|account number|\biban\b|\bswift\b|credit card|debit card|tax (id|identification)|\bein\b|\bitin\b|driver'?s? licen[cs]e (number|#)|date of birth|\bdob\b|birth ?date|maiden name|salary|compensation|\bpay\b|pay rate|hourly rate|\bwage|\bctc\b|criminal|convict|felony|arrest|lawsuit|litigation|\blegal\b|legally|citizenship|citizen\b|immigration|\bvisa\b|sponsor|clearance|polygraph|national id|\bamount\b|gender|\brace\b|ethnic|veteran|disabilit|religio|sexual|marital|pregnan|medical condition"

PROFILE_FIELDS = [
    ("Current job title", "currentJobTitle"),
    ("Current employer", "currentEmployer"),
    ("Total years of professional experience", "yearsOfExperience"),
    ("Years leading teams", "yearsLeadingTeams"),
    ("Skills", "skillsSummary"),
    ("Highest education", "educationLevel"),
    ("School", "school"),
    ("Graduation year", "graduationYear"),
    ("Field of study", "fieldOfStudy"),
    ("Certifications", "certifications"),
    ("Languages", "languages"),
    ("City", "city"),
    ("State", "state"),
    ("Country", "country"),
    ("Time zone", "timeZone"),
    ("Willing to relocate", "willingToRelocate"),
    ("Availability", "availabilityAnswer"),
    ("About", "aboutMeAnswer"),
    ("Key project", "projectAnswer"),
    ("Strengths", "strengthsAnswer"),
]


class LLMError(Exception):
    pass


def stripThinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I)
    text = re.sub(r"^.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"<think>.*$", "", text, flags=re.S | re.I)
    return text.strip()


class LLMClient:
    def __init__(self, url: str, model: str, timeout: float = 90, retries: int = 3, apiKey: str = "") -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.apiKey = apiKey

    @classmethod
    def fromEnv(cls) -> Optional["LLMClient"]:
        load_dotenv(ENV_PATH)
        url = (os.getenv("LLM_URL") or "").strip()
        model = (os.getenv("LLM_MODEL") or "").strip()
        if not url or not model:
            return None
        try:
            timeout = float(os.getenv("LLM_TIMEOUT") or 90)
        except ValueError:
            timeout = 90
        apiKey = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        return cls(url, model, timeout, apiKey=apiKey)

    def local(self) -> bool:
        return bool(re.search(r"localhost|127\.0\.0\.1|0\.0\.0\.0", self.url))

    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.apiKey}"} if self.apiKey else {}

    def hint(self) -> str:
        if self.local():
            return f"Start Ollama, then run: ollama pull {self.model}"
        return "Check LLM_URL, LLM_MODEL and LLM_API_KEY in .env"

    def check(self) -> str:
        if not self.local() and not self.apiKey:
            return f"{self.url} needs an API key. Set LLM_API_KEY in .env."
        response = None
        for attempt in range(2):
            try:
                response = requests.get(f"{self.url}/models", headers=self.headers(), timeout=20)
                break
            except requests.RequestException as e:
                lastError = type(e).__name__
                if attempt == 0:
                    time.sleep(2)
        if response is None:
            return f"{self.url} is not reachable ({lastError}). {self.hint()}"
        if response.status_code in (401, 403):
            return f"{self.url} rejected the API key (HTTP {response.status_code}). Check LLM_API_KEY in .env."
        if response.status_code == 429:
            return f"{self.url} returned HTTP 429. The account is rate limited or has no credit balance."
        if response.status_code != 200:
            return f"{self.url} answered HTTP {response.status_code}. {self.hint()}"
        try:
            ids = [m.get("id", "") for m in response.json().get("data", [])]
        except ValueError:
            return f"{self.url} returned an unreadable model list. {self.hint()}"
        wanted = {self.model, self.model + ":latest"}
        if ids and not wanted & set(ids):
            return f"Model {self.model} is not available at {self.url}. {self.hint()}"
        return ""

    def body(self, system: str, user: str) -> Dict:
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0, "stream": False}
        if not self.local() and re.match(r"(gpt-[5-9]|o[1-9])", self.model):
            # OpenAI reasoning tiers reject temperature unless reasoning is explicitly off.
            body["reasoning_effort"] = "none"
        return body

    def dropUnsupported(self, body: Dict, error: str) -> str:
        lowered = error.lower()
        if not re.search(r"unsupported|not supported|unrecognized|unknown|invalid", lowered):
            return ""
        for name in OPTIONAL_PARAMS:
            if name in body and name in lowered:
                body.pop(name)
                return name
        return ""

    def chat(self, system: str, user: str) -> str:
        body = self.body(system, user)
        lastError = ""
        for attempt in range(self.retries + 1):
            try:
                response = requests.post(f"{self.url}/chat/completions", json=body, headers=self.headers(), timeout=self.timeout)
                if response.status_code != 200:
                    raise LLMError(f"HTTP {response.status_code}: {response.text[:200]}")
                content = response.json()["choices"][0]["message"]["content"]
                return stripThinking(content)
            except requests.Timeout:
                lastError = f"timed out after {self.timeout:.0f}s"
            except requests.ConnectionError:
                lastError = f"could not connect to {self.url}"
            except (LLMError, KeyError, IndexError, ValueError, requests.RequestException) as e:
                lastError = str(e)[:200]
                if self.dropUnsupported(body, lastError):
                    continue
            if attempt < self.retries:
                time.sleep(5 * (attempt + 1))
        raise LLMError(f"LLM request to {self.url}/chat/completions failed after {self.retries + 1} attempts: {lastError}")


class AnswerAssistant:
    SYSTEM = ("You answer job application questions for a candidate, using only the candidate profile below. "
              "Answers must be short, direct and truthful. Never invent employers, degrees, certifications, skills or experience that the profile does not support, "
              "and never add numbers, percentages, metrics, client names or results that are not written in the profile. "
              "For years of experience with a skill that does not appear anywhere in the profile, the answer is 0. "
              "For a skill that appears in the profile but whose years are not stated, give a conservative whole-number estimate that is never more than the total years of professional experience. "
              "The candidate is actively looking for a new role and is applying to this job. "
              "For questions about willingness, comfort or preferences, such as a fast-paced environment, teamwork, learning new tools or following company processes, answer positively unless the profile contradicts it. "
              "If the profile does not clearly support an answer, reply with exactly UNSURE.")

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.cache: Dict[Tuple, Tuple[Optional[object], str]] = {}

    def system(self) -> str:
        # /no_think suppresses qwen-style reasoning blocks on local models; to a hosted model it is just noise.
        return self.SYSTEM + (" /no_think" if self.client.local() else "")

    def profile(self) -> str:
        lines = []
        for label, name in PROFILE_FIELDS:
            value = getattr(config, name, "")
            if value not in ("", None, []):
                lines.append(f"{label}: {value}")
        skills = getattr(config, "skills", [])
        if skills:
            lines.append("Skill keywords: " + ", ".join(skills))
        lines.append("Job search status: actively looking and open to new opportunities")
        return "\n".join(lines)

    def mentionsProfileSkill(self, question: str) -> bool:
        text = question.lower()
        return any(re.search(r"(?<![a-z0-9])" + re.escape(skill.lower()) + r"(?![a-z0-9])", text) for skill in getattr(config, "skills", []))

    def sensitive(self, question: str) -> bool:
        return bool(re.search(SENSITIVE_PATTERN, question.lower()))

    def instructions(self, kind: str, options: List[str]) -> str:
        if kind == "choice":
            return "Reply with exactly one of these options, copied exactly, and nothing else:\n" + "\n".join(f"- {o}" for o in options)
        if kind == "multi":
            return "Reply with every option that truthfully applies, each copied exactly on its own line, and nothing else:\n" + "\n".join(f"- {o}" for o in options)
        if kind == "number":
            return "Reply with only a whole number, with no words or units."
        if kind == "short":
            return "Reply with a short phrase or one sentence, plain text."
        return "Reply in at most three sentences, first person, plain text, no markdown."

    def parse(self, kind: str, raw: str, options: List[str], question: str = "") -> Tuple[Optional[object], str]:
        text = raw.strip().strip("`").strip()
        text = re.sub(r"^(answer|reply)\s*:\s*", "", text, flags=re.I).strip().strip('"').strip()
        if not text or re.fullmatch(r"\W*unsure\W*", text, flags=re.I) or re.search(r"\bUNSURE\b", text):
            return None, "model unsure"
        if kind in ("choice", "multi"):
            lowered = [o.lower().strip() for o in options]
            lines = [re.sub(r"^[-*\d.)\s]+", "", line).strip().lower() for line in text.splitlines() if line.strip()]
            picked = []
            for line in lines:
                if line in lowered:
                    picked.append(options[lowered.index(line)])
            if not picked:
                contained = [o for o, l in zip(options, lowered) if l and l in text.lower()]
                if contained:
                    picked = [max(contained, key=len)]
            if not picked:
                return None, f"answer not in options: {text[:60]}"
            return (picked if kind == "multi" else picked[0]), ""
        if kind == "number":
            match = re.search(r"-?\d+(?:\.\d+)?", text)
            if not match:
                return None, f"not a number: {text[:60]}"
            number = match.group(0)
            if float(number) == 0 and self.mentionsProfileSkill(question):
                return None, "model unsure"
            if float(number) > float(getattr(config, "yearsOfExperience", 99) or 99) and re.search(r"\byears?\b", question.lower()) and not re.search(r"salary|pay|rate", question.lower()):
                number = str(getattr(config, "yearsOfExperience"))
            return (number[:-2] if number.endswith(".0") else number), ""
        return text[:1500], ""

    def answer(self, question: str, kind: str, options: Optional[List[str]] = None, jobTitle: str = "", company: str = "") -> Tuple[Optional[object], str, bool]:
        options = options or []
        key = (kind, question.strip().lower(), tuple(options), jobTitle, company)
        if key in self.cache:
            value, reason = self.cache[key]
            return value, reason, False
        if self.sensitive(question):
            result = (None, "legal, financial or personal-identity question")
        else:
            prompt = f"Candidate profile:\n{self.profile()}\n\nJob title: {jobTitle or 'unknown'}\nCompany: {company or 'unknown'}\n\nQuestion: {question.strip()}\n\n{self.instructions(kind, options)}"
            try:
                result = self.parse(kind, self.client.chat(self.system(), prompt), options, question)
            except LLMError as e:
                result = (None, str(e))
        self.cache[key] = result
        return result[0], result[1], True
