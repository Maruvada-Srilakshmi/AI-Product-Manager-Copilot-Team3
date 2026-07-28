import os
from dotenv import load_dotenv
from crewai import Agent, Crew, Process, Task, LLM

load_dotenv()

# Setup Gemini LLM using CrewAI's LLM interface
gemini_llm = LLM(
    model="gemini/gemini-2.5-flash",
    api_key=os.getenv("GEMINI_API_KEY")
)

# Agent 1: Analyzes feedback
feedback_agent = Agent(
    role="Feedback Agent",
    goal="Analyze user feedback and categorize issues.",
    backstory="You are an expert product researcher.",
    llm=gemini_llm,
    verbose=True
)

# Agent 2: Generates PRDs & User Stories
prd_agent = Agent(
    role="PRD Agent",
    goal="Create a mini PRD with user stories.",
    backstory="You are a Lead Product Manager.",
    llm=gemini_llm,
    verbose=True
)

def run_pipeline(user_feedback: str):
    task1 = Task(
        description=f"Analyze this customer feedback: '{user_feedback}'",
        expected_output="A summary of key feedback items.",
        agent=feedback_agent
    )
    task2 = Task(
        description="Convert the key items into User Stories and Acceptance Criteria.",
        expected_output="Markdown formatted User Story.",
        agent=prd_agent
    )

    crew = Crew(
        agents=[feedback_agent, prd_agent],
        tasks=[task1, task2],
        process=Process.sequential
    )
    return crew.kickoff()