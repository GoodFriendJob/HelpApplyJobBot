import csv
import yaml
import os
from collections import defaultdict


def load_csv_questions(csv_path):
    questions_by_section = defaultdict(set)

    if not os.path.exists(csv_path):
        return questions_by_section

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row or not row.get('Question'):
                    continue

                question = row['Question'].strip().strip('"')
                if not question or len(question) < 3:
                    continue

                section = row.get('Section', '').strip()
                if section not in ('radio', 'dropdown', 'checkbox', 'inputField'):
                    section = 'inputField'

                status = row.get('Status', '').strip()
                if status and status.lower() != 'unanswered':
                    continue

                questions_by_section[section].add(question)
    except Exception as e:
        print(f"Error reading CSV: {e}")

    return questions_by_section


def load_yaml_questions(yaml_path):
    questions_by_section = defaultdict(set)

    if not os.path.exists(yaml_path):
        return questions_by_section

    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        for section in ['inputField', 'radio', 'dropdown', 'checkbox']:
            for key in (data.get(section) or {}).keys():
                questions_by_section[section].add(str(key).lower())
    except Exception as e:
        print(f"Error reading YAML: {e}")

    return questions_by_section


def get_default_answer(question, section):
    q = question.lower()

    if section == 'radio':
        if 'w2' in q or 'contract' in q:
            return 'Yes'
        if 'clearance' in q or 'secret' in q:
            return 'None'
        if 'local' in q or 'ohio' in q or 'california' in q:
            return 'No'
        if 'yes' in q or 'willing' in q or 'comfortable' in q or 'able' in q:
            return 'Yes'
        return 'No'

    elif section == 'inputField':
        if 'location' in q:
            return 'Remote'
        if 'platform' in q or 'solifi' in q or 'infol' in q:
            return 'No'
        return ''

    elif section in ('dropdown', 'checkbox'):
        return ''

    return ''


def process_manual_answers():
    csv_path = 'data/Manual Answer Questions.csv'
    yaml_path = 'additionalQuestions.yaml'

    csv_questions = load_csv_questions(csv_path)
    yaml_questions = load_yaml_questions(yaml_path)

    with open(yaml_path, 'r', encoding='utf-8') as f:
        yaml_data = yaml.safe_load(f) or {}

    added_count = 0

    for section in ['inputField', 'radio', 'dropdown', 'checkbox']:
        if section not in yaml_data:
            yaml_data[section] = {}

        for question in csv_questions.get(section, set()):
            if question.lower() not in yaml_questions[section]:
                answer = get_default_answer(question, section)
                yaml_data[section][question] = answer
                added_count += 1

    if added_count > 0:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_data, f, allow_unicode=True, sort_keys=False)
        print(f"\n✓ Added {added_count} new questions to additionalQuestions.yaml")
    else:
        print("No new questions to add (all are already in YAML)")


if __name__ == '__main__':
    process_manual_answers()
