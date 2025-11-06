# 🤖 Paraphrase AI Telegram Bot

## 📘 Overview
A **Python-based AI Telegram Bot** that uses **Gemini API** for multilingual paraphrasing (e.g., English and Amharic), integrated with **Firebase** for authentication and tracking.  
The bot limits daily paraphrasing, encourages user verification and referrals, and supports multiple Gemini API keys.

---

## ⚙️ Core Features

### 1. 🧩 User Workflow

#### Step 1 — Start Interaction
- When a user sends `/start`, the bot replies:
  - **Welcome message:** “Welcome! Send your message.”
  - After the user sends a message → bot asks:  
    **“How many paraphrased versions do you want?”**  
    Displays two horizontally aligned inline buttons:  
    - `2`  
    - `4`

#### Step 2 — Paraphrasing
- If the user selects **2**, the bot generates **2 paraphrased versions**.  
- If the user selects **4**, it generates **4 versions**.  
- The **last message** (second or fourth paraphrased message) includes two inline buttons:
  - **Add More**
  - **New Message**

#### Step 3 — Continue Paraphrasing
- If the user clicks **Add More**:
  - If they previously chose **2**, generate **2 more** paraphrases.  
  - If they chose **4**, generate **4 more**.  
  - The last message again contains the two buttons (**Add More** / **New Message**).
- If the user clicks **New Message**, the bot resets:
  - Asks again, “How many paraphrased versions do you want?”  
  - Shows the two inline buttons (`2` / `4`).

---

### 2. 🔐 Verification System
- Each user can generate **up to 10 paraphrased versions** freely.  
- When attempting the **11th version**, the bot sends:
Please verify your account.
With an inline **Verify** button linking to the external **verification page**.
- Once verified:
- The user is **never asked again** for verification.
- The verification message (with the link) will be **auto-deleted after 24 hours**.

---

### 3. 🚦 Daily Usage Limit & Referral System
- Each user can generate **20 paraphrased messages per day**.
- When they reach the limit:
- The bot replies:  
  “You’ve reached your daily limit! Invite others to continue.”  
  And sends their **unique invite link**.
- For **each invited new user**, the inviter earns **+20 paraphrase credits**.
- Example: inviting **10 users** → **200 paraphrases** unlocked.

---

### 4. 🧠 Paraphrasing Command Logic

**Prompt used for Gemini API:**

Paraphrase the following post without changing its original languages.
Some posts may contain multiple languages (for example, English and Amharic).
In such cases, paraphrase each section in its respective language — English parts in English, Amharic parts in Amharic.
Ensure that the total word count of the paraphrased version is approximately equal to the original post.


#### Additional Conditions:
- Telegram messages have a character limit.
- If the original message **exceeds ~150 words**:
  - The bot **summarizes or shortens** the paraphrased version to around **150 words**.
- If the message is **≤150 words**, keep the **word count similar** to the original.
- Prevent exceeding **Gemini API’s free tier word limit** per request.

---

### 5. 👨‍💼 Admin Features

#### Admin Authentication
- Admin triggers authentication with a **unique command**:
/dkfhgkjfhgdfh

- The bot recognizes this command as **admin entry**.
- Then requests the **password** stored in Firebase (hashed using `bcrypt`).
- Once authenticated, the admin is saved in Firebase and **never asked again**.

#### Daily Report
- Every 24 hours, if any admin exists in Firebase:
- The bot sends an **automatic report** containing:
  - Total number of users who interacted with the bot
  - Total paraphrased messages generated in the last 24 hours

---

### 6. 🔄 Gemini API Key Rotation
- A list of Gemini API keys is stored in `.env` as a **JSON array**.
- The bot tracks total paraphrased messages since startup.
- If total paraphrases **exceed 1300 within 24 hours**, it automatically:
- Switches to the **next Gemini API key** in the list.
- Continues the rotation sequentially.

---

## 🔑 Environment Variables (.env)

| Variable | Description |
|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `FIREBASE_KEY` | Firebase credentials |
| `GEMINI_APIS` | JSON array of Gemini API keys |
| `ADMIN_PASSWORD_HASH` | Admin password (bcrypt hashed) |
| `ADMIN_UNIQUE_STRING` | Unique admin command trigger |
| `VERIFICATION_LINK` | Verification link for user |

---

## 🧩 Implementation Notes

- **Framework:** `python-telegram-bot`  
- **AI Model:** Google **Gemini API**  
- **Database:** Firebase (Firestore)  
- **Concurrency:** Use `asyncio` for non-blocking requests  
- **Admin Authentication:** `bcrypt` for password hashing  
- **API Key Management:** Automatic rotation after quota limit

---

## 📂 Suggested Project Structure

main.py
├── handlers/
│ ├── user_handler.py
│ ├── admin_handler.py
│ └── paraphrase_handler.py
├── utils/
│ ├── firebase_utils.py
│ ├── gemini_utils.py
│ ├── auth_utils.py
│ └── helpers.py
├── .env
└── requirements.txt


---

## ⚙️ Dependencies (requirements.txt)
python-telegram-bot
firebase-admin
google-generativeai
bcrypt
python-dotenv
asyncio


---

## 🧭 Final Behavior Summary

| Stage | Description |
|--------|-------------|
| `/start` | Welcome → send message → choose paraphrase count |
| `2` / `4` | Generates 2 or 4 paraphrased versions |
| `Add More` | Generates additional paraphrases of the same message |
| `New Message` | Starts a new paraphrasing session |
| Verification | After 10 versions, verify via link (once only) |
| Daily Limit | Max 20 paraphrases/day; invite friends to earn more |
| Admin | Authenticates once; receives daily usage stats |
| Gemini API | Rotates after 1300 paraphrases per 24h |

---

## 🧾 License
This bot is intended for educational and research use.  
All API keys, tokens, and credentials must remain confidential.
