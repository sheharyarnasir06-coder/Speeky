"""
US-52: Standard HR Behavioral Interview (STAR Method Focus)

Behavioral HR questions ko STAR framework (Situation/Task/Action/Result)
ke hisaab se evaluate karta hai, missing parts pe follow-up poochta hai,
aur exceptions (hypothetical answer, negative tone, rambling) handle karta hai.
"""

import logging
import random

logger = logging.getLogger(__name__)

STAR_QUESTIONS = [
    "Tell me about a time you overcame a challenge at work.",
    "Describe a situation where you had to work with a difficult team member.",
    "Tell me about a time you missed a deadline. What happened?",
    "Give an example of when you had to solve a problem with limited resources.",
    "Tell me about a time you took initiative on a project.",
]

STAR_PARTS = ["SITUATION", "TASK", "ACTION", "RESULT"]

MISSING_PART_FOLLOWUPS = {
    "SITUATION": "Can you tell me a bit more about the context — where and when this happened?",
    "TASK": "What exactly was your responsibility or goal in that situation?",
    "ACTION": "What specific steps did you personally take?",
    "RESULT": "What was the final outcome of that action?",
}


class STARInterviewSession:
    def __init__(self, conversation_engine, persona_engine):
        self.conv = conversation_engine
        self.persona = persona_engine
        self.current_question = None
        self.rambling_word_threshold = 90
        self.attempts_on_current_question = 0

    def start(self):
        self.persona.start_session()
        self.current_question = random.choice(STAR_QUESTIONS)
        self.attempts_on_current_question = 0
        return {"status": "ok", "ai_message": self.current_question}

    def submit_answer(self, user_text):
        self.attempts_on_current_question += 1

        word_count = len(user_text.split())
        analysis = self._analyze_with_llm(user_text)

        if analysis.get("HYPOTHETICAL") == "yes":
            return {
                "status": "clarify",
                "ai_message": "That's a good approach, but could you give me a specific real-world example from your past experience?",
                "star_analysis": analysis,
            }

        if analysis.get("NEGATIVE_TONE") == "yes":
            return {
                "status": "reframe",
                "ai_message": (
                    "I'd encourage you to describe that experience a bit more diplomatically — "
                    "focus on what you learned rather than criticising others. "
                    "Could you try rephrasing your answer?"
                ),
                "star_analysis": analysis,
                "tone_penalty": True,
            }

        if analysis.get("RAMBLING") == "yes":
            return {
                "status": "interrupt",
                "ai_message": "I understand the background now. What specific actions did you take to resolve it?",
                "star_analysis": analysis,
            }

        missing_parts = [p for p in STAR_PARTS if analysis.get(p) == "no"]
        if missing_parts:
            next_missing = missing_parts[0]
            return {
                "status": "follow_up",
                "ai_message": MISSING_PART_FOLLOWUPS[next_missing],
                "star_analysis": analysis,
                "missing_parts": missing_parts,
            }

        return {
            "status": "complete",
            "ai_message": "Great, that was a well-structured answer covering the full situation, task, action, and result.",
            "star_analysis": analysis,
        }

    def _analyze_with_llm(self, user_text):
        persona_prompt = self.persona.get_effective_prompt(user_text)

        analysis_prompt = f"""{persona_prompt}

You are analysing a candidate's behavioral interview answer for the STAR method.

Candidate's answer:
\"\"\"{user_text}\"\"\"

Respond ONLY in this exact format, one line per item, answer strictly "yes" or "no":
SITUATION: <yes/no>
TASK: <yes/no>
ACTION: <yes/no>
RESULT: <yes/no>
HYPOTHETICAL: <yes/no> (yes if the candidate spoke about a hypothetical/future scenario instead of a real past event)
NEGATIVE_TONE: <yes/no> (yes if the candidate is complaining about or insulting a former employer/colleague)
RAMBLING: <yes/no> (yes ONLY if the answer is long, mostly background/context, with little to no mention of concrete actions taken)
"""

        raw_response = self.conv.generate_with_system_prompt(
            user_text=user_text,
            system_prompt=analysis_prompt,
            use_history=False,
        )

        return self._parse_analysis(raw_response)

    @staticmethod
    def _parse_analysis(raw_response):
        result = {key: "no" for key in STAR_PARTS + ["HYPOTHETICAL", "NEGATIVE_TONE", "RAMBLING"]}
        for line in raw_response.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().upper()
            value = value.strip().lower()
            if key in result:
                result[key] = "yes" if "yes" in value else "no"
        return result

    def generate_scorecard(self, final_analysis):
        present = [p for p in STAR_PARTS if final_analysis.get(p) == "yes"]
        missing = [p for p in STAR_PARTS if final_analysis.get(p) == "no"]
        score = int((len(present) / len(STAR_PARTS)) * 100)

        return {
            "score": score,
            "star_present": present,
            "star_missing": missing,
            "summary": (
                f"You covered {len(present)}/4 STAR elements ({', '.join(present) or 'none'}). "
                f"Missing: {', '.join(missing) or 'none'}."
            ),
        }


"""
US-48: Interview-in-Your-Market Scenario Execution (INT-US-10)
"""

KNOWN_INDUSTRIES = {
    "banking": "monthly sales/deposit targets, customer relationship management, and regulatory compliance",
    "telecom": "customer complaint resolution, network/service targets, and competitive market pressure",
    "textile": "production deadlines, export quality standards, and factory floor coordination",
}

WESTERNIZED_RED_FLAGS = [
    "disrupt", "awesome", "crush it", "hustle", "rockstar", "ninja",
    "synergy", "circle back", "touch base", "move the needle",
]

FALLBACK_INDUSTRY_NOTE = (
    "general Pakistani corporate expectations such as punctuality, respect for "
    "seniority, and meeting assigned targets"
)

ROMAN_URDU_WORDS = ["mujhe", "apni", "acha", "lagta", "hai", "kaam", "karna", "bohat", "aap", "hum"]


class LocalMarketInterviewSession:
    def __init__(self, conversation_engine):
        self.conv = conversation_engine
        self.industry = None
        self.turns = []

    def set_industry(self, industry_text):
        self.industry = industry_text.strip()
        self.turns = []

    def _build_persona_prompt(self):
        industry = self.industry or "general corporate"
        known_context = KNOWN_INDUSTRIES.get(industry.lower(), FALLBACK_INDUSTRY_NOTE)

        return f"""You are a senior HR manager at a Pakistani {industry} company.
You conduct interviews in a formal, respectful tone that reflects Pakistani
corporate workplace culture and hierarchy.

Relevant context for this sector: {known_context}.

STRICT RULES (do not break these):
- Never use casual Western startup language such as "disrupt", "awesome",
  "crush it", "hustle", "rockstar", "synergy", "circle back".
- Always respond in English only.
- Keep the tone formal and hierarchy-conscious, not casual or overly friendly.
- Ask questions relevant to the {industry} sector and Pakistani corporate norms
  (target achievement, respect for seniors, professional commitment).
"""

    def get_question(self):
        persona_prompt = self._build_persona_prompt()
        instruction = (
            "Ask ONE behavioral/HR interview question suited to this sector and "
            "Pakistani corporate context. Only output the question, nothing else."
        )

        question = self.conv.generate_with_system_prompt(
            user_text=instruction,
            system_prompt=persona_prompt,
            use_history=False,
        )

        question, was_reset = self._check_and_fix_persona_break(question, persona_prompt, instruction)
        return {
            "status": "ok",
            "ai_message": question.strip(),
            "persona_reset_triggered": was_reset,
        }

    def submit_answer(self, user_text):
        if self._is_mostly_non_english(user_text):
            return {
                "status": "language_reminder",
                "ai_message": (
                    "I noticed your response was in Urdu. Since this platform "
                    "focuses on English fluency practice, could you please try "
                    "answering in English?"
                ),
            }

        self.turns.append(user_text)
        return {
            "status": "recorded",
            "ai_message": "Thank you, noted. Let's continue.",
        }

    def generate_scorecard(self):
        if not self.turns:
            return {"status": "no_answers", "summary": "No answers recorded yet."}

        persona_prompt = self._build_persona_prompt()
        combined_answers = "\n---\n".join(self.turns)

        feedback_instruction = f"""Review the candidate's answers below and give
short feedback (3-4 sentences) specifically evaluating how well they matched
Pakistani corporate communication traits: respect for hierarchy, target-orientation,
and professional tone. Be specific, not generic.

Candidate's answers:
\"\"\"{combined_answers}\"\"\"
"""

        feedback = self.conv.generate_with_system_prompt(
            user_text=feedback_instruction,
            system_prompt=persona_prompt,
            use_history=False,
        )

        feedback, _ = self._check_and_fix_persona_break(feedback, persona_prompt, feedback_instruction)
        return {"status": "ok", "summary": feedback.strip()}

    def _check_and_fix_persona_break(self, text, persona_prompt, original_instruction):
        text_lower = text.lower()
        broke_persona = any(flag in text_lower for flag in WESTERNIZED_RED_FLAGS)

        if not broke_persona:
            return text, False

        reinforced_prompt = persona_prompt + (
            "\n\nIMPORTANT: Your previous response used overly casual Western "
            "phrasing. Regenerate your response in a strictly formal, Pakistani "
            "corporate HR tone, avoiding all casual startup language."
        )
        fixed_text = self.conv.generate_with_system_prompt(
            user_text=original_instruction,
            system_prompt=reinforced_prompt,
            use_history=False,
        )
        return fixed_text, True

    @staticmethod
    def _is_mostly_non_english(text):
        if not text.strip():
            return False

        non_ascii_count = sum(1 for ch in text if ord(ch) > 127)
        if (non_ascii_count / max(len(text), 1)) > 0.3:
            return True

        words = text.lower().split()
        urdu_word_count = sum(1 for w in words if w.strip(".,!?") in ROMAN_URDU_WORDS)
        return urdu_word_count >= 2


"""
US-50: University Admission Interview Simulation (INT-US-12)
"""

CASUAL_RED_FLAGS = [
    "wanna", "gonna", "yeah", "kinda", "sorta", "lol", "hang out", "cool", "dude",
]


class UniversityAdmissionSession:
    def __init__(self, conversation_engine):
        self.conv = conversation_engine
        self.degree = None
        self.turns = []

    def set_degree(self, degree_text):
        degree_text = (degree_text or "").strip()
        if degree_text == "" or degree_text.lower() in ["college", "university", "school", "degree"]:
            self.degree = None
            return {
                "status": "clarify_degree",
                "ai_message": "Could you tell me the specific degree or major you're applying for, such as Computer Science or MBA?",
            }
        self.degree = degree_text
        self.turns = []
        return {"status": "ok"}

    def _build_persona_prompt(self):
        degree = self.degree or "a general undergraduate program"
        return f"""You are a university admissions interviewer at a Pakistani university,
interviewing a candidate applying for {degree}.
Ask formal, respectful questions about academic goals, achievements,
extracurricular involvement, and fit for the program.
Keep your tone professional and encouraging.
"""

    def get_question(self):
        persona_prompt = self._build_persona_prompt()
        instruction = (
            "Ask ONE admission interview question about the candidate's academic "
            "goals, achievements, or extracurricular involvement. Only output the question."
        )
        question = self.conv.generate_with_system_prompt(
            user_text=instruction, system_prompt=persona_prompt, use_history=False,
        )
        return {"status": "ok", "ai_message": question.strip()}

    def submit_answer(self, user_text):
        text_lower = user_text.lower()
        if any(flag in text_lower for flag in CASUAL_RED_FLAGS):
            return {
                "status": "casual_tone_flag",
                "ai_message": "That's a great point, but try to keep your tone a bit more formal for an admission interview — could you rephrase that professionally?",
            }

        check_prompt = f"""Candidate's answer: "{user_text}"
Is this answer completely off-topic from academic goals (e.g. only talking about
video games, hobbies, unrelated topics with no connection to academics)?
Reply with only "yes" or "no"."""
        off_topic_check = self.conv.generate_with_system_prompt(
            user_text=check_prompt, system_prompt="You are a strict evaluator.", use_history=False,
        )
        if "yes" in off_topic_check.lower():
            return {
                "status": "off_topic",
                "ai_message": "That's interesting! Now, could you connect that back to your academic goals or interests?",
            }

        self.turns.append(user_text)
        return {"status": "recorded", "ai_message": "Thank you, noted. Let's continue."}

    def generate_scorecard(self):
        if not self.turns:
            return {"status": "no_answers", "summary": "No answers recorded yet."}

        persona_prompt = self._build_persona_prompt()
        combined = "\n---\n".join(self.turns)
        feedback_instruction = f"""Review these admission interview answers and give
short feedback (3-4 sentences) on the candidate's passion, clarity, and personal
narrative structure (does their story flow logically from interest to achievement to goal?).

Answers:
\"\"\"{combined}\"\"\"
"""
        feedback = self.conv.generate_with_system_prompt(
            user_text=feedback_instruction, system_prompt=persona_prompt, use_history=False,
        )
        return {"status": "ok", "summary": feedback.strip()}