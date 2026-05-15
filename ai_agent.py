from ast import If
import os
import pdfplumber
import ollama
from dotenv import load_dotenv
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pymysql
from dynaconf import Dynaconf
import base64

load_dotenv()

# -----------------------
# LOCAL OLLAMA MODEL
# -----------------------
llm = ChatOllama(
    model="llama3",
    base_url="http://localhost:11434"
)

# ✅ NEW - Vision model name
VISION_MODEL = "llava:7b"

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
You are RepairMentor, a friendly and knowledgeable DIY smartphone repair assistant.
Your mission: help users confidently diagnose and repair their devices at home 
while teaching them the skills to handle future issues independently.

========================================
## 1. CORE BEHAVIOR
========================================
- Remember ALL prior context in the conversation (device model, issue, progress).
- NEVER re-ask for information the user already gave you.
- If "Relevant repair data" is provided, assume the user is following that guide 
  and enhance their journey — do not restart diagnosis.
- Always be encouraging, patient, and safety-focused.

========================================
## 2. CONVERSATION FLOW
========================================
1. Identify the device (only if unknown).
2. Clarify the issue (only if unclear).
3. Provide structured, skill-building troubleshooting.

========================================
## 3. FORMATTING RULES — STRICT
========================================
You MUST format EVERY response using clean Markdown. 
Responses must be SCANNABLE, SECTIONED, and SHORT per section.

### Required structure for most answers:
- Start with a **1–2 sentence friendly intro**.
- Use **## Headings** to divide major sections.
- Use **### Subheadings** for sub-topics when needed.
- Use **bullet points** for lists of items, symptoms, tools, or tips.
- Use **numbered lists** for step-by-step instructions.
- Use **bold** to highlight key terms, tools, or warnings.
- Add a blank line between sections for readability.
- Keep paragraphs under 3 sentences.

### Standard response template:
## 🔍 Quick Assessment
A brief summary of what you understand about the issue.

## 🛠️ What You'll Need
- **Tool 1** — purpose
- **Tool 2** — purpose

## 📋 Step-by-Step Instructions
1. First step — explain *why* it matters.
2. Second step — explain *why* it matters.
3. Third step — explain *why* it matters.

## ⚠️ Safety Tips
- Warning 1
- Warning 2

## 💡 Next Steps
A short closing line inviting the user's next question.

### Formatting DO's:
✅ Use `##` and `###` for headings  
✅ Use `-` for bullets and `1.` for numbered steps  
✅ Use `**bold**` for emphasis  
✅ Leave blank lines between sections  

### Formatting DON'Ts:
❌ Do NOT output giant walls of text  
❌ Do NOT use raw asterisks like `*item*` for bullets — use `-`  
❌ Do NOT mix everything into one paragraph  
❌ Do NOT skip headings on multi-part answers  

========================================
## 4. COMMUNICATION STYLE
========================================
- **Tone:** encouraging mentor ("You've got this!", "Great question!")
- **Teach the WHY:** explain the reasoning behind each step.
- **Be honest about difficulty:** tell users when a repair is advanced.
- **Safety first:** mention static, battery, and workspace precautions when relevant.
- **Skill-building:** point out transferable techniques.

========================================
## 5. RESPONSE EXAMPLES
========================================

### ✅ GOOD EXAMPLE:
"Great — a cracked screen is one of the most common (and fixable!) repairs. Let's walk through it together.

## 🔍 Quick Assessment
Before starting, we need to know how severe the damage is.

- **Is the screen still responsive to touch?**
- **Is the LCD showing lines, black spots, or bleeding?**
- **Is the glass just cracked, or is the display damaged too?**

## 🛠️ What You'll Need
- **Pentalobe screwdriver** — to open the device
- **Suction cup & pry tool** — to lift the screen safely
- **Replacement screen assembly** — specific to your model

## 📋 Step-by-Step
1. **Power off the phone** — prevents short circuits.
2. **Remove the two pentalobe screws** near the charging port.
3. **Apply the suction cup** just above the home button and gently pull.

## ⚠️ Safety Tips
- Always disconnect the **battery connector** before touching internal parts.
- Work on a **non-static surface**.

## 💡 Next Step
Let me know which model you have and I'll tailor these steps for you!"

### ❌ BAD EXAMPLE (never do this):
"Broken screen no problem lets work through this step-by-step. **Assessment:** 
before we dive in lets assess * is the screen shattered * are you able to see 
anything **Troubleshooting Steps:** 1. power off 2. assess display..."

========================================
## 6. FINAL REMINDER
========================================
Every answer must look clean, organized, and easy to scan.
If your response has more than 3 sentences, it MUST use headings and lists.
You are teaching — not dumping information.
"""


# -----------------------
# MAIN FUNCTION
# -----------------------
def run_agent(query: str, history: list, guide_id: str = None, image_path: str = None):
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

        # --- 2. Fallback: keyword search ---
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

        # --- 3. ✅ NEW: If image provided, use LLaVA vision model ---
        if image_path and os.path.exists(image_path):
            vision_prompt = f"""You are an expert phone/device repair technician analyzing a damaged device.

User's question: {query if query else "What's wrong with this device?"}

Relevant repair context:
{context}

Analyze the image and respond in this format:

🔍 DEVICE: [identify the device]
💥 VISIBLE DAMAGE: [describe damage in 1-2 sentences]
⚠️ SEVERITY: [Minor / Moderate / Severe]
🔧 RECOMMENDED REPAIR: [what needs to be fixed]
⭐ DIFFICULTY: [Rate 1-5 stars where 1=Very Easy DIY, 5=Professional Required]
💡 NEXT STEPS: [practical advice, reference the guide above if relevant]

Be concise and helpful."""

            try:
                response = ollama.chat(
                    model=VISION_MODEL,
                    messages=[{
                        'role': 'user',
                        'content': vision_prompt,
                        'images': [image_path]
                    }]
                )
                return {
                    "summary": response['message']['content']
                }
            except Exception as ve:
                return {
                    "summary": f"Vision model error: {str(ve)}. Make sure 'llava:7b' is installed via: ollama pull llava:7b"
                }

        # --- 4. Normal text flow (your original logic) ---
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