import yaml
import os
import re
import sys
from answer_generator import AnswerGenerator

sys.stdout.reconfigure(encoding='utf-8')


def normalize_text(text: str) -> str:
    """Normalize text for comparison"""
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()


def find_similar_answer(question: str, section: str, answers: dict) -> str:
    """Find a similar answer from existing answers"""
    q_norm = normalize_text(question)

    for existing_q, existing_ans in answers.get(section, {}).items():
        if isinstance(existing_ans, dict):
            existing_ans = existing_ans.get("answer", "")

        if not existing_ans:
            continue

        existing_q_norm = normalize_text(existing_q)

        if len(existing_q_norm) >= 12 and f" {existing_q_norm} " in f" {q_norm} ":
            return str(existing_ans)

    return None


def process_all_pending():
    """Process all pending questions and add answers to additionalQuestions.yaml"""

    pending_path = "pendingQuestions.yaml"
    answers_path = "additionalQuestions.yaml"

    if not os.path.exists(pending_path):
        print("No pendingQuestions.yaml found")
        return

    try:
        with open(pending_path, "r", encoding="utf-8") as f:
            pending = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error reading pendingQuestions.yaml: {e}")
        return

    try:
        with open(answers_path, "r", encoding="utf-8") as f:
            answers = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error reading additionalQuestions.yaml: {e}")
        return

    ag = AnswerGenerator()
    total_added = 0
    unknown_count = 0

    print("Processing all pending questions...\n")

    for section in ["inputField", "radio", "dropdown", "checkbox"]:
        if section not in answers:
            answers[section] = {}

        pending_questions = list((pending.get(section) or {}).items())

        if not pending_questions:
            continue

        print(f"Processing {section} ({len(pending_questions)} questions):")

        for question, options in pending_questions:
            if question in answers[section] and answers[section][question]:
                continue

            option_list = None
            if section in ("radio", "dropdown", "checkbox") and options:
                if isinstance(options, str):
                    option_list = [opt.strip() for opt in options.split("|") if opt.strip()]
                elif isinstance(options, list):
                    option_list = options

            answer = ag.generate_answer(section, question, option_list)

            if answer == "UNKNOWN":
                similar_answer = find_similar_answer(question, section, answers)
                if similar_answer:
                    answer = similar_answer
                    print(f"  ~ {question[:70]}... -> Similar: {answer[:45]}")
                    answers[section][question] = answer
                    if section in pending:
                        del pending[section][question]
                    total_added += 1
                else:
                    unknown_count += 1
                    print(f"  ? {question[:70]}... -> UNKNOWN")
            else:
                answers[section][question] = answer
                if section in pending:
                    del pending[section][question]
                total_added += 1
                print(f"  + {question[:70]}... -> {answer[:50]}")

        print()

    with open(answers_path, "w", encoding="utf-8") as f:
        yaml.dump(answers, f, allow_unicode=True, sort_keys=False)

    with open(pending_path, "w", encoding="utf-8") as f:
        yaml.dump(pending, f, allow_unicode=True, sort_keys=False)

    print(f"\nSummary:")
    print(f"  Added to additionalQuestions.yaml: {total_added} answers")
    print(f"  Could not answer: {unknown_count} questions")
    print(f"  Remaining in pendingQuestions.yaml: {unknown_count}")


if __name__ == "__main__":
    process_all_pending()
