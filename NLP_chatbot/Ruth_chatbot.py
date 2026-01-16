#download ollama "https://ollama.com/download"
# ollama pull llama3
#ollama pull anindya/prem1b-sql-ollama-fp116
#for linux curl -fsSL https://ollama.com/install.sh | sh

import mysql.connector
from mysql.connector import Error
from langchain_community.llms import Ollama  # Ollama LLM wrapper
from datetime import datetime, timedelta
import re

# --- CONFIG ---
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'saran',
    'database': 'industrial_safety_db',
    'port': 3306
}

SQL_MODEL_NAME = "anindya/prem1b-sql-ollama-fp116"  # SQL generator
NLG_MODEL_NAME = "llama3"  # Natural language generator


class RuthSQLAssistant:
    def __init__(self, db_config, sql_model, nlg_model):
        self.db_config = db_config
        self.connection = None

        # SQL generator (strictly for query generation)
        self.sql_llm = Ollama(model=sql_model, temperature=0.0)

        # Natural language generator (for final answers)
        self.nlg_llm = Ollama(model=nlg_model, temperature=0.3)

        self.schema_text = ""
        self.setup_database()
        self.fetch_schema_with_samples()
        print("✅ Ruth: Initialized successfully!")

    def setup_database(self):
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            if self.connection.is_connected():
                print(f"✅ Ruth: Connected to database '{self.db_config['database']}'")
        except Error as e:
            print(f"❌ Ruth: Database connection error: {e}")
            raise

    def fetch_schema_with_samples(self):
        """Fetch schema + some sample values so the SQL model knows data types."""
        cursor = self.connection.cursor()
        cursor.execute("SHOW TABLES")
        tables = [t[0] for t in cursor.fetchall()]
        schema_parts = []
        for table in tables:
            cursor.execute(f"DESCRIBE {table}")
            columns = cursor.fetchall()
            col_texts = []
            for col in columns:
                name, col_type = col[0], col[1]
                cursor.execute(f"SELECT DISTINCT `{name}` FROM `{table}` LIMIT 5")
                samples = [str(r[0]) for r in cursor.fetchall() if r[0] is not None]
                sample_text = f" Sample values: {', '.join(samples)}" if samples else ""
                col_texts.append(f"{name} ({col_type}){sample_text}")
            schema_parts.append(f"Table `{table}` has columns: " + ", ".join(col_texts))
        cursor.close()
        self.schema_text = "\n".join(schema_parts)

    def preprocess_question(self, question):
        """Extract absolute or relative dates (today, tomorrow, yesterday) from the question."""
        q_lower = question.lower().strip()
        now = datetime.now()

        # --- Handle relative keywords ---
        if "today" in q_lower:
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(hour=23, minute=59, second=59, microsecond=0)
            return start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S')

        if "yesterday" in q_lower:
            start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = (now - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
            return start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S')

        if "tomorrow" in q_lower:
            start_date = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = (now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
            return start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S')

        # --- Handle specific absolute dates (e.g., 4th September 2025) ---
        date_match = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)(?:\s+(\d{4}))?', q_lower)
        if date_match:
            day, month_str, year_str = date_match.groups()
            month = datetime.strptime(month_str, "%B").month
            year = int(year_str) if year_str else now.year
            start_date = datetime(year, month, int(day), 0, 0, 0)
            end_date = datetime(year, month, int(day), 23, 59, 59)
            return start_date.strftime('%Y-%m-%d %H:%M:%S'), end_date.strftime('%Y-%m-%d %H:%M:%S')

        return None, None

    def generate_sql(self, question):
        """Generate SQL using Prem1B-SQL model."""
        start_date, end_date = self.preprocess_question(question)
        date_hint = f"Use timestamp BETWEEN '{start_date}' AND '{end_date}' for the date filter." if start_date else ""

        prompt = f"""
You are a SQL generation AI. Generate a valid SQL query for MySQL ONLY.
Do not explain anything. Only give the SQL.
Use the following schema:
{self.schema_text}
User question: "{question}"

IMPORTANT INSTRUCTIONS:
- Do NOT add any timestamp/date filters unless the question explicitly mentions a date.
{date_hint}
"""
        sql = self.sql_llm.invoke(prompt).strip()
        if "```" in sql:
            sql = sql.split("```")[1].split("```")[0].strip()
        return sql.rstrip(';')

    def execute_sql(self, query):
        """Run the generated SQL on the database."""
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(query)
            results = cursor.fetchall()
            cursor.close()
            return results
        except Error as e:
            print(f"❌ Ruth: SQL execution error: {e}")
            return None

    def summarize_results(self, question, results):
        """Convert raw SQL results into human-friendly answers using NLG model."""
        if not results:
            return "I couldn't find any records matching your query."

        rows_text = "\n".join([", ".join(f"{k}: {v}" for k, v in row.items()) for row in results])

        prompt = f"""
You are Ruth, a helpful assistant.
The user asked: "{question}"
The SQL query returned these results:
{rows_text}

Write a **short, direct answer** (1–2 sentences max).
Be clear and concise. Do not add extra commentary or questions.
"""
        answer = self.nlg_llm.invoke(prompt).strip()
        return answer

    def ask(self, question):
        try:
            sql_query = self.generate_sql(question)
            print(f"💡 Ruth: Generated SQL:\n{sql_query}")
            results = self.execute_sql(sql_query)
            return self.summarize_results(question, results)
        except Exception as e:
            return f"❌ Ruth encountered an error: {e}"

    def close(self):
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("✅ Ruth: Database connection closed")


# --- Run Ruth AI ---
def main():
    ruth = RuthSQLAssistant(DB_CONFIG, SQL_MODEL_NAME, NLG_MODEL_NAME)
    print("\n💬 Ruth: Hello! Ask me questions about your database.\n(Type 'quit' to exit)\n")

    while True:
        question = input("👤 You: ").strip()
        if question.lower() in ["quit", "exit", "bye"]:
            print("💬 Ruth: Goodbye!")
            break
        if not question:
            continue
        answer = ruth.ask(question)
        print(f"💬 Ruth: {answer}\n")

    ruth.close()


if __name__ == "__main__":
    main()
