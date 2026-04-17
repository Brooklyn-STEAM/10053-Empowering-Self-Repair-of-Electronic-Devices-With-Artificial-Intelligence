from dotenv import load_dotenv
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

# -----------------------
# LOCAL OLLAMA MODEL
# -----------------------
llm = ChatOllama(
    model="llama3",
    base_url="http://localhost:11434"
)

# -----------------------
# SYSTEM PROMPT
# -----------------------
SYSTEM_PROMPT = """
You are a structured diagnostic AI repair assistant.

You MUST follow this strict conversation flow:

========================
RULE 1: MEMORY BEHAVIOR
========================
- If the user already gave device info (model, type, etc.), DO NOT ask again
- Never repeat questions that have already been answered

========================
RULE 2: CONVERSATION FLOW
========================
Step 1: Identify device (ONLY if unknown)
Step 2: Identify issue (ONLY if unknown)
Step 3: Give troubleshooting steps

========================
RULE 3: NO LOOPING
========================
- Do NOT re-ask for device type if it is already mentioned
- Do NOT restart the diagnosis process mid-conversation
- Continue from last known information

========================
RULE 4: BE STATEFUL
========================
Assume all previous user messages are part of context
and do not ignore them.

========================
STYLE:
========================
- Be structured
- Be calm and technical
- Be step-by-step
"""

# -----------------------
# MAIN FUNCTION
# -----------------------
def run_agent(query: str):
    try:
        response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=query)
        ])

        return {
            "summary": response.content
        }

    except Exception as e:
        return {
            "summary": f"Error: {str(e)}"
        }