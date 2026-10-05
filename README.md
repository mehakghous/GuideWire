# \# GuideWire

# 

# AI-powered interactive desktop tutorial and task assistance system, scoped to Blender.

# GuideWire turns YouTube tutorials, written instructions or direct questions into guided

# on-screen sessions: it watches the Blender window, highlights the exact tool for each step,

# and checks whether the step was completed.

# 

# FAST University, Karachi Campus. Department of SE. FYP 2026-27.

# 

# \## Team

# 

# | Member | Area | Folder |

# |---|---|---|

# | Ayesha Raza | Tutorial understanding and step generation | `/ingestion` |

# | Umaima Fatima | Screen capture, UI detection and overlay | `/vision` |

# | Mehak | App UI, accounts, session engine | `/app` |

# 

# \## Project structure

# 

# ```

# /ingestion   YouTube transcripts, step generation (Ayesha)

# /vision      screen capture, grounding, overlay (Umaima)

# /app         PyQt6 UI, accounts, session engine (Mehak)

# /shared      shared data model and step format

# /docs        SRS, SDS and diagrams

# /tests       tests for all components

# ```

# 

# \## Required versions

# 

# \- Python 3.11

# \- Blender: \*\*<write the exact version here, e.g. 5.x.x>\*\* (everyone uses the same one)

# \- Blender layout: default layout, screen at 1920x1080 (or the same display scaling),

# &#x20; so that screenshots are comparable across team members

# 

# \## Setup

# 

# 1\. Clone the repo.

# 2\. Create and activate a virtual environment:

# ```

# &#x20;  py -3.11 -m venv venv

# &#x20;  venv\\Scripts\\activate

# ```

# 3\. Install dependencies:

# ```

# &#x20;  pip install -r requirements.txt

# ```

# 4\. Create your own `.env` file by copying `.env.example`, then fill in your API keys.

# &#x20;  \*\*Never commit `.env`.\*\*

# 

# \## Git rules

# 

# \- Nobody pushes directly to `main`.

# \- Each person works on their own branch, named `yourname/short-task-name`.

# \- Open a pull request for every change. Another team member reviews it before it is merged.

# \- Pull `main` before starting a new branch.

# 

# \## Documents

# 

# SRS, SDS and diagrams are kept in `/docs`. Log every change in the Document History table.

