#!/usr/bin/env python

import yaml
import os
import sys
import re
import time
import uuid

sys.stdout.reconfigure(encoding='utf-8')

try:
    import requests
except ImportError:
    requests = None

try:
    from llm import LLMClient, LLMError, SENSITIVE_PATTERN
except ImportError:
    LLMClient = None
    LLMError = Exception
    SENSITIVE_PATTERN = ""

try:
    import config
except ImportError:
    config = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_path(path):
    """Absolute path for a setting that may be written relative to the project root."""
    if not path:
        return ""
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def default_profile_path():
    """The resume the AI answers from: config.resumePath first, then the usual fallbacks."""
    for candidate in (getattr(config, "resumePath", ""), "profile.txt", "resume.pdf"):
        resolved = resolve_path(candidate)
        if resolved and os.path.isfile(resolved):
            return resolved
    return ""


class AnswerGenerator:
    SYSTEM = ("You answer job application questions for a candidate, using only the candidate profile given to you. "
              "Answers must be short, direct and truthful. Never invent employers, degrees, certifications, skills, "
              "metrics or client names that the profile does not support. "
              "If the profile does not clearly support an answer, reply with exactly UNKNOWN.")

    def __init__(self, profile_path=None):
        self.pending_path = "pendingQuestions.yaml"
        self.answers_path = "additionalQuestions.yaml"
        self.client = None
        self.llm_available = False
        self.profile_path = resolve_path(profile_path) if profile_path else default_profile_path()
        self.profile_text = self.load_profile(self.profile_path)
        self.check_llm()

    def load_profile(self, profile_path):
        # An empty profile silently disables every AI answer, so say so rather than failing quietly.
        if not profile_path or not os.path.isfile(profile_path):
            print("⚠ No resume found (checked config.resumePath, profile.txt, resume.pdf) - AI answers disabled")
            return ""

        if profile_path.lower().endswith(".pdf"):
            try:
                import PyPDF2
                with open(profile_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    text = "".join((page.extract_text() or "") for page in reader.pages)
            except Exception as e:
                print(f"⚠ Could not read {profile_path}: {str(e)[:120]} - AI answers disabled")
                return ""
        else:
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    text = f.read()
            except OSError as e:
                print(f"⚠ Could not read {profile_path}: {str(e)[:120]} - AI answers disabled")
                return ""

        text = text.strip()
        if not text:
            print(f"⚠ No text could be extracted from {profile_path} (scanned image?) - AI answers disabled")
            return ""

        try:
            shown = os.path.relpath(profile_path, BASE_DIR)
        except ValueError:
            shown = profile_path
        print(f"✓ Resume loaded: {shown} ({len(text)} chars)")
        return text

    def check_llm(self):
        if LLMClient is None or not requests:
            print("⚠ LLM support unavailable (needs requests and python-dotenv) - using smart defaults\n")
            return False
        self.client = LLMClient.fromEnv()
        if not self.client:
            print("⚠ No LLM_URL/LLM_MODEL in .env - using smart defaults\n")
            return False
        problem = self.client.check()
        if problem:
            print(f"⚠ {problem}")
            print("⚠ Falling back to smart defaults\n")
            self.client = None
            return False
        self.llm_available = True
        where = "local" if self.client.local() else self.client.url
        print(f"✓ LLM available ({self.client.model} via {where}) - using AI for complex questions\n")
        return True

    def is_uuid(self, text):
        try:
            uuid.UUID(str(text))
            return True
        except ValueError:
            return False

    def call_llm(self, prompt):
        if not self.llm_available or not self.client:
            return None
        try:
            result = (self.client.chat(self.SYSTEM, prompt) or "").strip()
        except LLMError:
            return None
        if result and result.upper() not in ["UNKNOWN", "I DON'T KNOW"]:
            return result
        return None

    def match_option(self, answer, options):
        text = answer.strip().lower()
        for opt in options:
            if opt.strip().lower() == text:
                return opt
        hits = [opt for opt in options if opt.strip().lower() and opt.strip().lower() in text]
        return max(hits, key=len) if hits else None

    def ask_llm(self, section, question, options=None):
        if not self.llm_available or not self.profile_text:
            return None

        # ~12k chars covers a full two-page resume; at $0.10 per 1M input tokens that is ~$0.0003 a question.
        profile = f"Candidate profile:\n{self.profile_text[:12000]}\n\n"

        if options:
            option_text = "\n".join(f"- {opt}" for opt in options)
            prompt = (f"{profile}Question: {question}\n\nOptions:\n{option_text}\n\n"
                      "Reply with exactly one option, copied exactly, and nothing else.\n"
                      "When the question asks for a skill or proficiency level that the profile does not state outright, "
                      "infer it from the years of hands-on use and the projects, roles and responsibilities shown above, "
                      "and pick the option a recruiter reading this profile would agree with. "
                      "A technology used in production across several years or multiple senior roles is not a beginner "
                      "level. Do not understate what the profile demonstrates, and do not claim more than it shows. "
                      "Reply UNKNOWN only if no option can be supported at all.")
        else:
            prompt = f"{profile}Question: {question}\n\nAnswer in 1-2 sentences, plain text."

        answer = self.call_llm(prompt)
        if answer and options:
            return self.match_option(answer, options)
        return answer

    def is_sensitive(self, question):
        # Legal, financial and protected-characteristic questions must not be guessed by a model.
        return bool(SENSITIVE_PATTERN) and bool(re.search(SENSITIVE_PATTERN, question.lower()))

    def get_smart_answer(self, section, question, options=None):
        mapped = self.get_mapped_answer(section, question)
        if mapped:
            return mapped
        return self.get_default_answer(section, options, self.is_sensitive(question))

    def get_mapped_answer(self, section, question):
        q = question.lower().strip()

        if section == "inputField":
            mapping = {
                "first name": "Paula",
                "last name": "Carvajal",
                "email": "josh.ariasduran@gmail.com",
                "phone": "6871072627",
                "linkedin": "https://www.linkedin.com/in/jose-arias-duran-7a8b67416",
                "github": "https://github.com/GoodFriendJob",
                "portfolio": "https://github.com/GoodFriendJob",
                "location": "Remote",
                "experience": "6+ years",
                "healthcare": "I have 6+ years of experience with scalable systems and can quickly ramp up on healthcare domain requirements",
                "qa": "Yes, I have experience with QA testing frameworks and automated testing",
                "education": "Bachelor's Degree in Computer Science",
                "toil": "Reducing toil means automating repetitive operational tasks to free up time for innovation and reliability improvements",
                "design": "I'm interested in leveraging technical expertise to support this role and the broader team goals",
                "manage": "I manage multiple requests by prioritizing based on impact and urgency, maintaining clear communication with stakeholders",
                "architecture": "I approach system design by balancing scalability, maintainability, and performance while considering business requirements",
                "challenge": "I've overcome technical challenges by breaking down complex problems, researching solutions, and collaborating with the team",
                "leadership": "I lead by example, providing clear documentation, mentoring junior developers, and making decisions collaboratively",
                "impact": "I've directly contributed to shipping products that improved user experiences and generated significant value for the business",
                "failure": "I learn from setbacks by analyzing root causes, implementing preventive measures, and sharing knowledge with the team",
                "conflict": "I approach disagreements professionally by listening to all perspectives and finding solutions that align with project goals",
                "skill": "Python, Java, TypeScript, React, Angular, AWS, Docker, PostgreSQL, MongoDB, Kubernetes",
                "project": "Built full-stack web applications, REST APIs, microservices, and AI-powered features using Python, Java, TypeScript, React, Angular and AWS",
                "why": "I'm excited about this opportunity to leverage my full-stack and AI engineering expertise to build impactful solutions",
                "background": "I'm a Senior AI & Full-Stack Software Engineer with 6+ years of experience building production-ready applications",
                "salary": "I'm flexible and open to a competitive offer within your budgeted range",
                "availability": "Within two weeks",
                "visa": "I am authorized to work in the US without sponsorship",
                "relocation": "Open to relocation opportunities within the United States",
            }
            for key, value in mapping.items():
                if key in q:
                    return value
            return None

        if section == "radio":
            if self.is_uuid(question.split()[0] if ' ' in question else question):
                return "Yes"
            if any(kw in q for kw in ["visa", "sponsorship", "authorization", "citizen", "permanent"]):
                return "No"
            if any(kw in q for kw in ["willing", "comfortable", "interested", "able", "available"]):
                return "Yes"
            if any(kw in q for kw in ["relocate", "travel", "commute"]):
                return "Yes"
            if any(kw in q for kw in ["clearance", "secret", "security"]):
                return "None"
            if any(kw in q for kw in ["ohio", "local"]):
                return "No"
            if any(kw in q for kw in ["salary", "range"]):
                return "No"
            if any(kw in q for kw in ["agree", "consent", "accept"]):
                return "Yes"
            return None

        if section == "dropdown":
            if any(kw in q for kw in ["education", "degree"]):
                return "Bachelor's Degree"
            if any(kw in q for kw in ["experience", "years"]):
                return "5+ years"
            if any(kw in q for kw in ["notice"]):
                return "2 weeks"
            if any(kw in q for kw in ["start", "available"]):
                return "Within 2 weeks"
            if any(kw in q for kw in ["salary", "compensation"]):
                return "Competitive"
            if any(kw in q for kw in ["location", "where"]):
                return "Remote"
            if any(kw in q for kw in ["language", "english"]):
                return "Native or bilingual"
            return None

        if section == "checkbox":
            if self.is_uuid(question.split()[0] if ' ' in question else question):
                return "Yes"
            if any(kw in q for kw in ["agree", "consent", "acknowledge", "accept"]):
                return "Yes"
            if any(kw in q for kw in ["privacy", "policy", "terms"]):
                return "Yes"
            if any(kw in q for kw in ["ai", "artificial"]):
                return "Yes"
            if any(kw in q for kw in ["contact", "future", "message"]):
                return "Yes"
            if any(kw in q for kw in ["visa", "sponsorship"]):
                return "No"
            if any(kw in q for kw in ["disability", "gender", "race", "veteran"]):
                return "Prefer not to answer"
            return None

        return None

    def get_default_answer(self, section, options=None, sensitive=False):
        if options:
            if sensitive:
                opt_out = next((o for o in options if re.search(r"prefer not|decline|do not wish|choose not", o, re.I)), None)
                # Legal and protected-characteristic choices are never guessed, not even a safe-looking "Yes".
                return opt_out or "UNKNOWN"
            yes = next((o for o in options if o.strip().lower() in ("yes", "y")), None)
            # Guessing an arbitrary option would risk overstating; leave it for a human instead.
            return yes or "UNKNOWN"
        if section == "inputField":
            return "I have 6+ years of full-stack and AI engineering experience and I'm excited about this opportunity"
        return "Yes"

    def generate_answer(self, section, question, options=None):
        # Known facts (name, email, visa, consent) stay deterministic; only the rest costs a token.
        mapped = self.get_mapped_answer(section, question)
        if mapped and options:
            # A mapped value no option can accept is unusable; let the model choose from the real options.
            mapped = self.match_option(mapped, options)
        if mapped:
            return mapped

        sensitive = self.is_sensitive(question)
        if not sensitive:
            answer = self.ask_llm(section, question, options)
            if answer:
                return answer

        return self.get_default_answer(section, options, sensitive)

    def process_pending(self):
        if not os.path.exists(self.pending_path):
            print("No pendingQuestions.yaml found")
            return

        try:
            with open(self.pending_path, "r", encoding="utf-8") as f:
                pending = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error reading pendingQuestions.yaml: {e}")
            return

        try:
            with open(self.answers_path, "r", encoding="utf-8") as f:
                answers = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error reading additionalQuestions.yaml: {e}")
            return

        for section in ["inputField", "radio", "dropdown", "checkbox"]:
            if section not in answers:
                answers[section] = {}

        total_pending = sum(len(v) for v in pending.values() if v)
        print("=" * 80)
        print(f"GENERATING ANSWERS FOR {total_pending} PENDING QUESTIONS")
        print("=" * 80 + "\n")

        added = 0

        for section in ["inputField", "radio", "dropdown", "checkbox"]:
            section_questions = list((pending.get(section) or {}).items())
            if not section_questions:
                continue

            section_added = 0
            for question, options in section_questions:
                current_answer = answers[section].get(question, "")
                if current_answer and str(current_answer).strip() and str(current_answer).strip().lower() != "none":
                    continue

                option_list = None
                if section in ("radio", "dropdown", "checkbox") and options:
                    if isinstance(options, str):
                        option_list = [opt.strip() for opt in options.split("|") if opt.strip()]
                    elif isinstance(options, list):
                        option_list = options

                answer = self.generate_answer(section, question, option_list)

                # "UNKNOWN" means no answer could be justified; leave it pending for a human.
                if answer and answer != "UNKNOWN":
                    answers[section][question] = answer
                    if section in pending and question in pending[section]:
                        del pending[section][question]
                    added += 1
                    section_added += 1

            print(f"{section.upper()}: {section_added}/{len(section_questions)} answered")

        print("\n" + "=" * 80)
        print(f"RESULTS: Added {added} answers")
        print("=" * 80)

        try:
            with open(self.answers_path, "w", encoding="utf-8") as f:
                yaml.dump(answers, f, allow_unicode=True, sort_keys=False)

            with open(self.pending_path, "w", encoding="utf-8") as f:
                yaml.dump(pending, f, allow_unicode=True, sort_keys=False)

            print("\n✓ Updated additionalQuestions.yaml")
            print("✓ Updated pendingQuestions.yaml")

            answers_total = sum(len(v) for v in answers.values())
            pending_total = sum(len(v) for v in pending.values() if v)
            print(f"\nTotal answers: {answers_total}")
            print(f"Remaining pending: {pending_total}\n")

        except Exception as e:
            print(f"Error saving: {e}")


def main():
    print("\n" + "=" * 80)
    print("ANSWER GENERATOR - PROCESS ALL PENDING QUESTIONS")
    print("=" * 80 + "\n")

    generator = AnswerGenerator()
    generator.process_pending()

    print("✓ All pending questions processed!")
    print("✓ Your job bots are ready to apply!\n")


if __name__ == "__main__":
    main()
