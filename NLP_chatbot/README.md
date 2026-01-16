# Ruth SQL Assistant 🤖

Ask questions about your database in plain English and get answers.

## What It Does

- Ask questions like "How many accidents happened today?"
- Ruth converts your question to SQL
- Executes the query
- Gives you a simple answer

## Setup

### 1. Install Ollama

**Linux/Mac:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows:** Download from https://ollama.com/download

### 2. Download AI Models
```bash
ollama pull llama3
ollama pull anindya/prem1b-sql-ollama-fp16
```

### 3. Install Python Packages
```bash
pip install mysql-connector-python langchain-community
```

### 4. Configure Database

Edit these lines in the code:

```python
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'your_password',  # Change this
    'database': 'your_database',   # Change this
    'port': 3306
}
```

## Run It

```bash
python ruth_assistant.py
```

## Example Usage

```
👤 You: How many workers are there?
💬 Ruth: There are 150 workers in the database.

👤 You: Show accidents from yesterday
💬 Ruth: There were 2 accidents yesterday.

👤 You: quit
💬 Ruth: Goodbye!
```

## Use in Your App

```python
from ruth_assistant import RuthSQLAssistant

# Setup
ruth = RuthSQLAssistant(DB_CONFIG, SQL_MODEL_NAME, NLG_MODEL_NAME)

# Ask questions
answer = ruth.ask("How many incidents today?")
print(answer)

# Close when done
ruth.close()
```

## Common Issues

**"Can't connect to database"**
- Check your password and database name
- Make sure MySQL is running

**"Model not found"**
- Run: `ollama pull llama3`

**Ollama not responding**
- Check if Ollama is running: `ollama list`

## Support

Questions? Create an issue on GitHub.

---

Made for Industrial Safety Databases
