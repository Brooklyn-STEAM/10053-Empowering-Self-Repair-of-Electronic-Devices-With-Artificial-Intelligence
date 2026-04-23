from ast import If
import os
import pdfplumber
from dotenv import load_dotenv
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pymysql
from dynaconf import Dynaconf


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



If the user's current guide is provided in the "Relevant repair data" section,
you MUST assume the user is performing that exact repair.
Do not ask for device model or issue again—instead provide help specific to the steps and tools listed.

"""

# -----------------------
# MAIN FUNCTION
# -----------------------
def run_agent(query: str, history: list, guide_id: str = None):
    try:
        context = ""

        # --- 1. Fetch specific guide if guide_id is present ---
        if guide_id:
            guide_details = get_guide_by_id(guide_id)
            if guide_details:
                pdf_text = ""
                pdf_path = guide_details.get("PDF_Path")
                if pdf_path:
                    full_pdf_path = os.path.join("static", pdf_path)
                    pdf_text = extract_pdf_text(full_pdf_path)

                context = f"""
*** CURRENT GUIDE THE USER IS VIEWING ***
Guide Name: {guide_details['Name']}
Difficulty: {guide_details['Difficulty']}
Time Estimate: {guide_details['Time_Estimate']}
Tools Required: {guide_details['Tools']}
Step-by-Step Instructions (from database):
{guide_details['Steps']}

--- FULL PDF CONTENT ---
{pdf_text if pdf_text else "PDF text not available."}
-----------------------------------------
"""
            else:
                context = "The user is on a guide page but details could not be loaded.\n"

        # --- 2. Fallback: keyword search (only if no guide_id or if you want both) ---
        db_results = search_repair_guides(query)

        if db_results:
            if not context:
                context = "Relevant repair guides found:\n"
            for r in db_results:
                context += f"""
Guide: {r['Name']}
Difficulty: {r['Difficulty']}
Time: {r['Time_Estimate']}
Tools: {r['Tools']}
Steps: {r['Steps']}
------------------
"""
        elif not context:
            context = "No matching repair guides found."

        # --- 3. Build message history (unchanged) ---
        messages = [SystemMessage(content=SYSTEM_PROMPT)]

        for msg in history[-6:]:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))

        messages.append(HumanMessage(content=f"""
User question: {query}

Relevant repair data:
{context}

Use the provided guide information whenever possible.
If the user is currently viewing a specific guide (listed above), assume they are working on that repair.
Give troubleshooting advice in the context of that guide.
"""))

        response = llm.invoke(messages)

        return {
            "summary": response.content
        }

    except Exception as e:
        return {
            "summary": f"Error: {str(e)}"
        }
    
def get_guide_by_id(guide_id: str):

    config = Dynaconf(settings_file=["settings.toml", ".env"])
    conn = pymysql.connect(
        host="db.steamcenter.tech",
        user=config.USER,
        password=config.password,
        database="blueprint",
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()
    sql = """
    SELECT 
        rg.Name, 
        rg.Steps, 
        rg.Tools, 
        rg.Difficulty, 
        rg.Time_Estimate, 
        rg.PDF_Path
    FROM RepairGuides rg
    WHERE rg.ID = %s
    LIMIT 1
    """
    cursor.execute(sql, (guide_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def search_repair_guides(query: str):
    import pymysql
    from dynaconf import Dynaconf

    config = Dynaconf(settings_file=["settings.toml", ".env"])

    conn = pymysql.connect(
        host="db.steamcenter.tech",
        user=config.USER,
        password=config.password,
        database="blueprint",
        cursorclass=pymysql.cursors.DictCursor
    )

    cursor = conn.cursor()

    sql = """
    SELECT rg.Name, rg.Steps, rg.Tools, rg.Difficulty, rg.Time_Estimate
    FROM RepairGuides rg
    JOIN RepairItems ri ON rg.Repair_Item_ID = ri.ID
    WHERE ri.Name LIKE %s
    LIMIT 2
    """

    keywords = query.split()
    like_query = "%" + "%".join(keywords) + "%"

    cursor.execute(sql, (like_query,))
    results = cursor.fetchall()

    conn.close()

    return results

def extract_pdf_text(pdf_path: str) -> str:
    """Return extracted text from PDF file."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return text[:3000]  # Limit to avoid token overflow
    except Exception as e:
        return f"[PDF extraction failed: {e}]"