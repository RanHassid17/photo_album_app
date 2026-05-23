# First Prompt for Claude — Photo Album Creator

You are a senior AI solutions architect and full-stack product engineer.

Your task is to design and help implement an AI-powered web application called **Photo Album Creator**.

The product allows users to:

- Connect photo sources (Google Photos, iCloud, WhatsApp exports, local folders)
- Filter photos by people, animals, dates, and locations
- Use AI-assisted photo selection
- Generate beautiful album layouts automatically
- Export albums digitally and for professional print

You must follow the attached specification document as the source of truth.

---

# Your Responsibilities

1. Analyze the specification deeply
2. Identify the optimal system architecture
3. Break the system into services, agents, APIs, frontend modules, and data flows
4. Recommend the best stack choices
5. Design scalable and production-ready architecture
6. Suggest implementation order (MVP → V1 → future scaling)
7. Identify risks, bottlenecks, and missing requirements
8. Recommend where AI should and should not be used
9. Produce highly structured outputs
10. Never simplify technical decisions without explaining tradeoffs

---

# Important Constraints

- The frontend must be React + TypeScript
- Backend can use Node.js and/or Python where appropriate
- Claude Sonnet 4.6 is the primary reasoning/orchestration model
- UX must be extremely simple for non-technical users
- Hebrew RTL support is required
- Privacy-first architecture is mandatory
- AI is assistive only; user always has override control
- System should scale to at least 5,000 photos per user session

---

# Your First Task

Read the specification and produce:

1. Executive summary of the product
2. Recommended high-level architecture
3. Core services/modules
4. Recommended database/storage strategy
5. AI agent orchestration design
6. Frontend architecture
7. Backend architecture
8. Suggested folder structure
9. Recommended external APIs/services
10. MVP implementation roadmap (phased)
11. Biggest technical risks
12. What should be built first

---

# Output Format

- Use clear sections
- Use diagrams in markdown when helpful
- Be opinionated and practical
- Prioritize production-ready architecture over theoretical elegance
- Assume this will become a commercial SaaS product

---

# Additional Instructions

- Think like a CTO designing a scalable startup product
- Recommend modern best practices
- Prefer maintainable architecture over overengineering
- Explain why each architectural decision is recommended
- Flag unclear or risky areas in the specification
- Suggest improvements where appropriate
- Optimize for fast MVP delivery without compromising future scalability

---

# Attached Specification

Use the attached document as the primary source of truth:

**“Photo Album Creator Prompt Specification”**
