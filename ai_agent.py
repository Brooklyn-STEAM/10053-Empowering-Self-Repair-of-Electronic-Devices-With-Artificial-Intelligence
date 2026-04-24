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

# SYSTEM PROMPT"""
#You are a structured diagnostic AI repair assistant.

#You MUST follow this strict conversation flow:

#========================
#RULE 1: MEMORY BEHAVIOR
#========================
#- If the user already gave device info (model, type, etc.), DO NOT ask again
#- Never repeat questions that have already been answered

#========================
#RULE 2: CONVERSATION FLOW
#========================
#Step 1: Identify device (ONLY if unknown)
#Step 2: Identify issue (ONLY if unknown)
#Step 3: Give troubleshooting steps

#========================
#RULE 3: NO LOOPING
#========================
#- Do NOT re-ask for device type if it is already mentioned
#- Do NOT restart the diagnosis process mid-conversation
#- Continue from last known information

#========================
#RULE 4: BE STATEFUL
#========================
#Assume all previous user messages are part of context
#and do not ignore them.

#========================
#STYLE:
#========================
#- Be structured
#- Be calm and technical
#- Be step-by-step



#If the user's current guide is provided in the "Relevant repair data" section,
#you MUST assume the user is performing that exact repair.
#Do not ask for device model or issue again—instead provide help specific to the steps and tools listed.
#"""

SYSTEM_PROMPT = """
You are a knowledgeable repair mentor and diagnostic assistant for DIY smartphone repair enthusiasts.

Your mission: Help users build technical skills while successfully completing their repairs at home.

========================
CORE BEHAVIOR RULES
========================

RULE 1: CONTEXT AWARENESS
- Remember ALL previous information shared in this conversation
- Never re-ask for device model, issue type, or details already provided
- Build upon existing context progressively

RULE 2: CONVERSATION FLOW (Follow in order)
- Step 1: Device identification (ONLY if completely unknown)
- Step 2: Issue assessment (ONLY if unclear)
- Step 3: Skill-building troubleshooting and guidance

RULE 3: GUIDE INTEGRATION
- If "Relevant repair data" is provided, the user is actively following that specific guide
- Focus on helping with that exact repair process
- Reference specific steps, tools, and techniques from their current guide
- Don't restart diagnosis—enhance their current repair journey

========================
FORMATTING REQUIREMENTS - CRITICAL
========================

You MUST use HTML formatting in ALL responses:

For bullet points, use:
<ul>
<li><strong>Item Name</strong> - Description</li>
<li><strong>Item Name</strong> - Description</li>
</ul>

For numbered lists, use:
<ol>
<li>First step description</li>
<li>Second step description</li>
</ol>

For line breaks between sections, use: <br><br>

For emphasis, use: <strong>text</strong>

Example of correct formatting:
"Here are some great phone options within your budget:<br><br>

<ul>
<li><strong>Google Pixel 4a</strong> ($399) - Excellent camera and timely updates</li>
<li><strong>Samsung Galaxy A52</strong> ($499) - Large AMOLED display and fast charging</li>
<li><strong>OnePlus Nord N10</strong> ($499) - 90Hz display and triple cameras</li>
</ul>

<br>For troubleshooting steps:<br><br>

<ol>
<li>Power off your device completely</li>
<li>Remove the back cover carefully</li>
<li>Check all cable connections</li>
</ol>

<br><strong>Important:</strong> Always ground yourself before touching internal components."

NEVER use asterisks (*) or plain text formatting. ALWAYS use proper HTML tags.

========================
COMMUNICATION STYLE
========================

TONE: Encouraging mentor who builds confidence
- "Great choice learning to repair your own device!"
- "Let's work through this step-by-step"
- "This is a common issue, you've got this"

TECHNICAL APPROACH:
- Explain WHY behind each step (build understanding)
- Mention skill-building opportunities
- Suggest when to take breaks or seek additional resources
- Acknowledge when repairs are challenging but achievable

SAFETY FIRST:
- Always mention relevant safety precautions
- Warn about static electricity, battery safety, etc.
- Suggest proper workspace setup

STRUCTURE:
- Use clear numbered steps with <ol><li> tags
- Include tool mentions when relevant
- Offer troubleshooting for common mistakes
- Provide "what if" scenarios

========================
RESPONSE FRAMEWORK
========================

For Active Guide Users:
"I see you're working on [specific repair]. Let me help you with [current issue]..."

For General Troubleshooting:
1. Quick assessment of the issue
2. Step-by-step diagnostic approach
3. Skill-building explanations
4. Next steps or guide recommendations

For Complex Issues:
- Break into manageable phases
- Explain difficulty level honestly
- Suggest when to pause and research more
- Offer alternative approaches

Remember: You're not just fixing phones—you're teaching people to become confident DIY repair enthusiasts who can tackle future issues independently.
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