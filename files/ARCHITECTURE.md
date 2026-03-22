# AI Talent Agent Network - System Architecture

This document describes the architecture of the AI Talent Agent Network.

The system is designed as a **multi-agent collaboration network** composed of several layers.

---

# 1. Overall Architecture
User Layer
│
▼
Orchestration Layer
│
├───────────── Candidate Agent Hub
│
├───────────── Company Agent Hub
│
▼
Matching Network Layer
│
▼
Execution Layer
│
▼
Data Layer

---

# 2. User Layer

Provides interfaces for:

- Job seekers
- Companies
- System administrators

Typical interfaces include:

- Web dashboard
- Job application console
- Career assistant interface
- Company hiring assistant interface

---

# 3. Orchestration Layer

## Career Orchestrator

The Career Orchestrator acts as the central coordinator of the agent network.

Responsibilities:

- Receive user requests
- Route tasks to appropriate agents
- Manage workflow execution
- Aggregate results from agents
- Trigger human intervention when necessary

---

# 4. Candidate Agent Hub

This hub contains agents responsible for assisting job seekers.

## 4.1 Candidate Profile Agent

Purpose:

Create a structured representation of the candidate.

Input:

- Resume
- Portfolio
- LinkedIn / GitHub
- User questionnaire

Output:

- Candidate profile schema
- Skill graph
- Experience summary
- Career preferences

---

## 4.2 Career Strategy Agent

Purpose:

Determine job search direction and strategy.

Responsibilities:

- Analyze candidate profile
- Evaluate job market trends
- Recommend job categories
- Generate job application strategies

Output:

- Target roles
- Application priorities
- Job search strategy

---

## 4.3 Job Discovery Agent

Purpose:

Discover job opportunities across platforms.

Responsibilities:

- Search job boards
- Scrape company career pages
- Aggregate job listings
- Filter relevant positions

Output:

- Job pool
- Structured job descriptions

---

## 4.4 Application Agent

Purpose:

Execute job application tasks.

Responsibilities:

- Open job application pages
- Fill application forms
- Upload resumes
- Generate custom responses
- Submit applications

This agent uses browser automation tools.

---

## 4.5 Tracker Agent

Purpose:

Track and manage job applications.

Responsibilities:

- Record submitted applications
- Track interview invitations
- Update job status
- Provide follow-up reminders

---

# 5. Company Agent Hub

These agents assist companies in defining hiring needs.

---

## 5.1 Requirement Analysis Agent

Purpose:

Understand real hiring needs.

Input:

- Project description
- Team structure
- Business goals

Output:

- Whether hiring is necessary
- Required role types
- Required skill sets

---

## 5.2 Job Design Agent

Purpose:

Transform hiring needs into structured job roles.

Output:

- Job title
- Responsibilities
- Skill requirements
- Experience level
- Salary range

---

## 5.3 Company Profile Agent

Purpose:

Build structured company hiring profiles.

Information includes:

- Team composition
- Technology stack
- Hiring history
- Cultural values

---

## 5.4 Recruit Assist Agent

Purpose:

Assist companies in recruitment.

Capabilities:

- Candidate recommendation
- Interview question suggestions
- Candidate summaries
- Hiring analytics

---

# 6. Matching Network Layer

The Matching Network is the core intelligence layer.

It includes:

## Talent Ontology

A unified skill taxonomy that maps:

- Candidate skills
- Job requirements

---

## Match Engine

Computes candidate-job compatibility.

Inputs:

- Candidate profile
- Job description
- Company profile

Outputs:

- Match score
- Skill gap analysis
- Recommendation level

---

## Salary & Level Reasoner

Evaluates whether job requirements and salary are aligned with the market.

Capabilities:

- Detect unrealistic job requirements
- Recommend fair salary ranges
- Identify overqualified candidate scenarios

---

## Market Intelligence Agent

Analyzes global labor market trends.

Capabilities:

- Skill demand analysis
- Salary benchmarks
- Industry hiring trends

---

# 7. Execution Layer

Responsible for performing real-world actions.

## Browser Agent

Automates browser interactions such as:

- Page navigation
- Form filling
- Resume uploads

---

## Platform Adapters

Adapters translate platform-specific workflows.

Examples:

- China Job Platform Adapter
- Global ATS Adapter
- Remote Job Adapter
- Company Career Page Adapter

---

## Human Takeover Manager

Handles situations requiring human intervention:

- CAPTCHA verification
- SMS verification
- login authentication

---

# 8. Data Layer

The system stores multiple types of data.

## Structured Data

Stored in relational databases:

- Candidate profiles
- Job records
- Application status
- Company profiles

---

## Object Storage

Stores:

- Resumes
- Documents
- Screenshots
- Attachments

---

## Vector Database

Stores embeddings for:

- Skills
- Job descriptions
- Candidate experience

Used for semantic matching.

---

## Session Store

Caches temporary data such as:

- Browser sessions
- Task queues
- Execution states

---

# 9. System Philosophy

The architecture is designed based on the following principles:

1. Specialized agents perform focused tasks
2. Matching intelligence remains neutral between candidates and companies
3. Execution and reasoning are separated
4. Human intervention is supported when automation fails
5. The system can evolve into a decentralized talent network


# HireNet - System Architecture (v2.0)

This document describes the architecture of HireNet.

HireNet is not just a job application tool or a recruitment platform. It is a **task-first Human-Agent Labor Network** that decides how work should be completed by coordinating AI agents and human talent.

The core idea is:

> **Task first, then resource decision, then execution.**

Instead of assuming every business need should be solved by hiring people, the system first analyzes the task itself, then decides whether it should be completed by:

- AI Agents
- Human talent
- Human-Agent collaboration

---

# 1. Overall Architecture

## 1.1 High-Level Architecture Diagram

```text
┌──────────────────────────────────────────────────────────────┐
│                       Interface Layer                        │
│ Enterprise Console / Job Seeker Console / Agent Chat UI     │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    Orchestration Layer                       │
│ Career Orchestrator / Workflow Engine / Task Router         │
│ Human-in-the-loop Manager                                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                       Decision Layer                         │
│ Requirement Analysis Agent                                  │
│ Task Decomposition Agent                                    │
│ Resource Decision Engine                                    │
│ Job Design Agent                                            │
│ Matching Engine                                             │
└──────────────────────────────────────────────────────────────┘
                 │                               │
       ┌─────────┘                               └─────────┐
       ▼                                                   ▼
┌──────────────────────────────┐              ┌──────────────────────────────┐
│      Agent Resource Hub      │              │      Human Resource Hub      │
│ Coding / Data / Analysis     │              │ Candidate Profiles           │
│ Content / Browser / Ops      │              │ Recruit Pipeline             │
└──────────────────────────────┘              └──────────────────────────────┘
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────┐
│                       Execution Layer                        │
│ A2A Agent Invocation / Browser Agent / ATS Adapter          │
│ Platform Adapter / Task Runner                              │
└──────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────┐
│                    Data & Memory Layer                       │
│ User Info / Soft Memory / Notes / Candidate Memory          │
│ Company Memory / Task Records / Match Results / Logs        │
└──────────────────────────────────────────────────────────────┘
```

## 1.2 Why the Architecture Changed

The previous version of the system was primarily **job-first**:

```text
Candidate Profile → Job Discovery → Matching → Application
```

That architecture was suitable for an AI job assistant.

The new version is **task-first**:

```text
Task / Requirement → Analysis → Resource Decision → Execution
```

This change reflects the upgraded product vision:

- Work should not automatically become a job opening
- Some tasks should be completed directly by AI agents
- Some tasks still require human professionals
- Some tasks are best solved through Human-Agent collaboration

Therefore, the system center has shifted from a pure job-seeking workflow to a **decision-and-orchestration-driven labor network**.

---

# 2. Interface Layer

The Interface Layer provides the entry points for different users.

It includes:

- Enterprise Console
- Job Seeker Console
- Agent Chat Interface
- Internal Admin / Monitoring Console

## Responsibilities

- Receive enterprise requirements
- Receive job seeker goals
- Show task analysis results
- Show job recommendations and application progress
- Expose human takeover and confirmation interactions

---

# 3. Orchestration Layer

The Orchestration Layer is the system's central coordinator.

It ensures that the correct agents are called in the correct order and that long-running workflows remain traceable and recoverable.

## 3.1 Career Orchestrator

The Career Orchestrator acts as the main coordinator of the network.

### Responsibilities

- Receive user requests
- Decide which sub-agents should be called
- Route tasks between enterprise-side and candidate-side flows
- Aggregate outputs from multiple agents
- Trigger human intervention when needed

## 3.2 Workflow Engine

The Workflow Engine manages long-running workflows.

### Responsibilities

- Track task status
- Support pause / resume logic
- Handle retries and failures
- Maintain execution order
- Keep auditability of multi-step actions

## 3.3 Task Router

The Task Router directs work into the right path.

### Example

```text
Enterprise requirement
→ Decision Layer
→ Agent execution path OR Human recruitment path
```

## 3.4 Human-in-the-loop Manager

This module manages points where human confirmation is necessary.

### Responsibilities

- Pause execution for CAPTCHA / login verification / approvals
- Notify the user when manual action is required
- Resume workflows after confirmation

---

# 4. Decision Layer

The Decision Layer is the core intelligence layer of HireNet.

This is where the system decides how work should be completed.

## 4.1 Requirement Analysis Agent

### Purpose

Understand the real need behind an enterprise request.

### Input

- Project description
- Team structure
- Business goals
- Constraints and budget

### Output

- Core task objective
- Whether the company truly needs hiring
- Requirement summary

## 4.2 Task Decomposition Agent

### Purpose

Break complex requirements into smaller executable tasks.

### Example

```text
Build an AI product landing page
→ copywriting
→ UI design
→ frontend development
→ deployment
```

### Output

- Structured task list
- Task dependencies
- Task complexity labels

## 4.3 Resource Decision Engine

### Purpose

Determine whether each task should be completed by:

- Agents
- Humans
- Human-Agent collaboration

### Output

- Agent-executable tasks
- Human-required tasks
- Hybrid tasks
- Resource allocation recommendation

This is one of the most important modules in the entire system.

## 4.4 Job Design Agent

### Purpose

When the system determines that a human is needed, this agent transforms the task into a structured job definition.

### Output

- Job title
- Responsibilities
- Skill requirements
- Experience level
- Salary range suggestion

## 4.5 Matching Engine

### Purpose

Match tasks and jobs to the right resources.

### Matching Types

- Agent-task matching
- Human-task matching
- Candidate-job matching
- Human-Agent collaboration matching

---

# 5. Resource Layer

The Resource Layer contains the available execution resources.

The system explicitly separates resources into **Agent Resources** and **Human Resources**.

## 5.1 Agent Resource Hub

This hub contains AI agents that can directly execute work.

### Example Agents

- Coding Agent
- Data Agent
- Analysis Agent
- Content Agent
- Browser Agent
- Resume Agent
- Operations Agent

### Responsibilities

- Execute standardized or automatable tasks
- Return structured results to the orchestration layer
- Collaborate through A2A protocols

## 5.2 Human Resource Hub

This hub contains human candidates and recruitment resources.

### Includes

- Candidate profiles
- Skill graph
- Talent pool
- Recruitment pipeline status

### Responsibilities

- Provide human execution resources for tasks requiring expertise
- Support candidate matching and recruitment workflows

---

# 6. Candidate Agent Hub

Although HireNet has evolved beyond a job-seeking product, the candidate-side capabilities remain important.

## 6.1 Candidate Profile Agent

### Purpose

Create a structured representation of the candidate.

### Input

- Resume
- Portfolio
- LinkedIn / GitHub
- User questionnaire
- Historical activity

### Output

- Candidate profile schema
- Skill graph
- Experience summary
- Career preferences

## 6.2 Career Strategy Agent

### Purpose

Determine job search direction and strategy.

### Responsibilities

- Analyze candidate profile
- Evaluate job market trends
- Recommend job categories
- Generate application strategies

### Output

- Target roles
- Application priorities
- Job search strategy

## 6.3 Job Discovery Agent

### Purpose

Discover job opportunities across platforms.

### Responsibilities

- Search job boards
- Scrape company career pages
- Aggregate job listings
- Filter relevant positions

### Output

- Job pool
- Structured job descriptions

## 6.4 Application Agent

### Purpose

Execute job application tasks.

### Responsibilities

- Open job application pages
- Fill application forms
- Upload resumes
- Generate custom responses
- Submit applications

This agent uses browser automation tools.

## 6.5 Tracker Agent

### Purpose

Track and manage job applications.

### Responsibilities

- Record submitted applications
- Track interview invitations
- Update job status
- Provide follow-up reminders

---

# 7. Company Agent Hub

These agents help enterprise users express and structure their needs more accurately.

## 7.1 Requirement Analysis Agent

### Purpose

Understand real hiring and execution needs.

### Input

- Project description
- Team structure
- Business goals
- Existing team capabilities

### Output

- Whether hiring is necessary
- Required role types
- Required skill sets
- Tasks suitable for agents

## 7.2 Job Design Agent

### Purpose

Transform needs into structured job roles only when necessary.

### Output

- Job title
- Responsibilities
- Skill requirements
- Experience level
- Salary range

## 7.3 Company Profile Agent

### Purpose

Build structured company execution and hiring profiles.

### Information Includes

- Team composition
- Technology stack
- Hiring history
- Cultural values
- Existing operational capabilities

## 7.4 Recruit Assist Agent

### Purpose

Assist companies in recruitment execution.

### Capabilities

- Candidate recommendation
- Interview question suggestions
- Candidate summaries
- Hiring analytics

---

# 8. Execution Layer

The Execution Layer is responsible for performing real-world actions.

## 8.1 A2A Agent Invocation

### Purpose

Invoke external or internal agents through A2A-compatible interfaces.

### Responsibilities

- Send tasks to specialized agents
- Receive structured outputs
- Coordinate multi-agent execution

## 8.2 Browser Agent

### Purpose

Automate browser interactions.

### Capabilities

- Page navigation
- Form filling
- Resume uploads
- UI interaction

## 8.3 Platform Adapters

Adapters translate platform-specific workflows into a unified execution interface.

### Examples

- China Job Platform Adapter
- Global ATS Adapter
- Remote Job Adapter
- Company Career Page Adapter

## 8.4 Task Runner

### Purpose

Execute structured task sequences from the workflow layer.

### Responsibilities

- Run step-by-step tasks
- Handle status transitions
- Store execution results

---

# 9. Data & Memory Layer

The system stores multiple types of data and memory.

## 9.1 User Information

Stores basic user identity information.

## 9.2 Soft Memory

Stores persistent user preferences and long-term context.

### Example

- Career preferences
- Historical interaction summaries
- Long-term goals

## 9.3 Notes

Stores structured notes and intermediate records.

### Example

- Application history
- Enterprise task records
- Match explanations

## 9.4 Candidate Memory

Stores:

- Candidate profiles
- Skill graph
- Experience embeddings

## 9.5 Company Memory

Stores:

- Company requirements
- Historical decisions
- Hiring records

## 9.6 Task Records

Stores:

- Task decomposition results
- Resource decision results
- Execution path history

## 9.7 Logs and Audit Trails

Stores:

- Execution logs
- Failure logs
- Human takeover records
- Workflow transitions

---

# 10. Core System Flows

## 10.1 Enterprise Flow

```text
Enterprise requirement input
↓
Requirement Analysis Agent
↓
Task Decomposition Agent
↓
Resource Decision Engine
    ├─ Agent execution path
    │      ↓
    │   A2A Invocation / Task Runner
    │
    └─ Human execution path
           ↓
        Job Design Agent
           ↓
        Matching Engine
           ↓
        Recruitment execution
```

## 10.2 Job Seeker Flow

```text
Upload resume
↓
Candidate Profile Agent
↓
Career Strategy Agent
↓
Job Discovery Agent
↓
Matching Engine
↓
User confirmation
↓
Application Agent
↓
Tracker Agent
```

---

# 11. Design Principles

The architecture is designed based on the following principles:

1. **Task-first**: Start from the work to be done, not from predefined job openings.
2. **Human-Agent collaboration**: Treat agents and humans as two resource classes in the same labor network.
3. **Decision and execution separation**: Keep reasoning and action execution loosely coupled.
4. **Agent modularity**: Each agent should be focused and replaceable.
5. **Recoverability**: Long workflows must be pausable, resumable, and auditable.
6. **Scalability**: The system should evolve from job assistance to full labor infrastructure.

---

# 12. System Definition

HireNet is fundamentally:

> **An AI-driven Human-Agent Labor Orchestration System**

It is not just:

- a job board
- a recruitment platform
- a resume tool

It is a system that decides **how work should be completed** and coordinates the best combination of agents and humans to get it done.