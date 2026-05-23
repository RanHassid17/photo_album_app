# PROMPT SPECIFICATION DOCUMENT

### Photo Album Creator — AI-Powered Web Application

| Field | Value |
|---|---|
| **Document Title** | Prompt Specification — Photo Album Creator |
| **Project / System** | AI Photo Album Web Application |
| **Author** |  |
| **Version** | 1.0 |
| **Date** | 2026-05-23 |
| **Status** | Draft |

---

## 1. Purpose & Scope

**Purpose:**
Define the AI agents and prompts required to power a web application that allows users to create beautiful photo albums from multiple sources (Google Photos, iCloud, WhatsApp, local folders). The system uses AI for photo filtering, selection suggestions, and automatic album layout design.

**In Scope:**

- Photo import from Google Photos, iCloud, WhatsApp, and local folders
- AI-powered filtering by person, animal, date (month/year), and location
- Manual and AI-assisted photo selection
- AI-suggested album layout with manual override
- Comment/description fields per photo (above, below, or side)
- Digital album output (Lupa-style viewer)
- Print-ready output with folder organization by photo print size

**Out of Scope:**

- Direct print-shop integration (v1)
- Video clips in albums (v1)
- Real-time collaboration (v1)

---

## 2. System / Application Overview

- **System name:** Photo Album Creator (working title)
- **System type:** Web application (React frontend + Node.js/Python backend)
- **AI model / engine:** Claude Sonnet 4.6 (primary), Google Vision API / AWS Rekognition (photo analysis)

**Description:**
A web application that connects to the user's photo sources, uses computer vision AI to index and filter photos by face, animal, date, and location, then assists the user in selecting and arranging photos into a designed album. The album can be exported as a digital flipbook or as print-ready files organized by print size.

---

## 3. Target Audience & Users

- **Primary user persona:** Families and individuals who want to create personalized photo albums for gifts, events, or memories
- **Secondary users:** Professional photographers, event organizers, grandparents gifting printed albums
- **User technical literacy:** Non-technical to mixed — the UI must be intuitive without requiring technical knowledge
- **Language & locale:** Hebrew (primary), English (secondary), RTL layout support required

---

## 4. Prompt Goals & Success Criteria

### 4.1 Primary Goal

Enable a user to go from "I have photos scattered across Google Photos, iCloud, and WhatsApp" to a beautifully designed, ready-to-share or ready-to-print photo album in under 30 minutes, with AI doing the heavy lifting on filtering, selection, and layout.

### 4.2 Secondary Goals

- **Goal 1:** Accurate person and animal detection — filter results must match visually with ≥90% precision
- **Goal 2:** Smart layout — AI-suggested layouts must feel intentional, balanced, and visually appealing
- **Goal 3:** Seamless source integration — connecting Google Photos / iCloud / WhatsApp should require no manual file downloads
- **Goal 4:** Print readiness — exported folders must be organized by print size with correct DPI (300 DPI minimum)

### 4.3 Success Criteria

- User can connect at least one photo source within 2 minutes
- Filter results return in <5 seconds for libraries up to 5,000 photos
- AI photo selection proposes a coherent, diverse set of photos (no duplicates, good variety)
- AI layout suggestion fills the page attractively with no awkward whitespace
- Print export produces correctly sized, DPI-compliant files organized by print size
- User can override any AI decision at any step without losing progress

### 4.4 Anti-Goals

- The AI should not auto-delete or permanently discard any photo from the source library
- The system should not require the user to understand DPI or print formats
- Do not expose raw API keys or OAuth tokens to the frontend

---

## 5. Prompt Type & Format

| Attribute | Value |
|---|---|
| Prompt roles | System prompts per agent + tool-use calls |
| Interaction style | Multi-turn conversation (album creation wizard) + batch processing (photo indexing) |
| Input medium | Images (photos) + structured JSON (metadata) + user text (descriptions/comments) |
| Output format | JSON (filters, layouts, selections) + rendered HTML/CSS (album preview) + binary files (print export) |
| Max input tokens | ~32K per agent call (photos passed as URLs, not base64 where possible) |
| Max output tokens | ~4K per response |

---

## 6. Context & Background Information

- **Domain:** Consumer photography, digital media, print production

**Background the model needs:**
Each agent receives: (1) the user's photo library metadata index (JSON with photo IDs, dates, locations, existing captions, detected faces/labels), (2) current user session state (selected filters, chosen photos, current album layout), (3) user preferences set during onboarding (e.g. preferred style: modern/classic/playful).

**Dynamic context (retrieved at runtime):**

- Photo metadata from connected source APIs (Google Photos, iCloud, WhatsApp export)
- Face/label/location index built by the Vision Agent on first sync
- Current album state (selected photos, layout, comments)
- User's previous album history (for style learning)

**Static context (hardcoded in prompts):**

- Layout rules and design principles (golden ratio, visual weight balance)
- Print size standards (10x15, 13x18, 20x30 cm) and DPI requirements (300 DPI)
- Supported photo source capabilities and limitations

---

## 7. Inputs & Variables

| Variable | Description | Type / Format | Required? |
|---|---|---|---|
| `photo_source` | Connected source(s) | Enum: `google_photos`, `icloud`, `whatsapp`, `folder` | Yes |
| `filter_persons` | Selected person IDs to filter by | Array of face cluster IDs | No |
| `filter_animals` | Animal types to filter by | Array of strings: dog, cat, horse… | No |
| `filter_date_range` | Date range for photos | Object: `{from: YYYY-MM, to: YYYY-MM}` | No |
| `filter_locations` | Location names / geo areas | Array of strings or geo coordinates | No |
| `selection_mode` | Manual or AI-assisted selection | Enum: `manual`, `ai_suggest` | Yes |
| `album_page_count` | Target number of album pages | Integer | No |
| `album_style` | Design style preference | Enum: `modern`, `classic`, `playful`, `minimal` | No |
| `output_type` | Digital or print output | Enum: `digital`, `print` | Yes |
| `print_sizes` | Required print sizes (if print output chosen) | Array: `["10x15","13x18","20x30"]` | Conditional |

---

## 8. Expected Output Specification

- **Filter Agent output:**
  JSON array of photo objects matching all active filters: `[{id, url, date, location, persons[], labels[], caption}]`

- **Selection Agent output:**
  Ranked list of suggested photos with reasoning: `[{photo_id, score, reason: "best_of_day|unique_face|high_quality"}]`

- **Layout Agent output:**
  Album layout JSON: pages array, each page has a grid definition, photo placements (position, size, rotation), and comment block positions (`above|below|left|right`, max 150 chars per block)

- **Print Export output:**
  Folders organized by print size (e.g. `/export/10x15/`, `/export/13x18/`). Each photo resized and exported at 300 DPI minimum as TIFF or high-quality JPEG. Naming convention: `{album_name}_{page}_{position}.jpg`

- **Digital Album output:**
  Rendered HTML/CSS flipbook (Lupa-style) OR exportable PDF with embedded fonts and images. Shareable via link.

---

## 9. Tone, Style & Persona

| Dimension | Specification |
|---|---|
| Persona / role | "You are a creative album designer and photo curator. You care deeply about preserving memories beautifully. You are warm, encouraging, and detail-oriented." |
| Tone | Warm, friendly, encouraging — like a personal creative assistant |
| Voice | Second person ("I've selected 24 photos that tell your story...") |
| Writing style | Concise suggestions with brief reasoning; never overwhelming the user |
| Jargon level | No technical jargon — translate print/design terms into plain language |
| Cultural sensitivity | Hebrew RTL support; sensitive to family/religious occasions common in Israeli context |

---

## 10. Constraints & Restrictions

### 10.1 Privacy & Security

- Photos must never leave the user's account without explicit consent
- Face recognition data (clusters) must be stored locally or in user's private storage — never sent to third-party training
- OAuth tokens for Google Photos / iCloud must be stored server-side with encryption; never exposed to frontend
- WhatsApp media: only process from user-exported ZIP — no live WhatsApp access
- GDPR / Israeli privacy law compliance required for any stored photo metadata

### 10.2 Business Rules

- User can always override any AI suggestion — AI is an assistant, not a gatekeeper
- Minimum album size: 1 page; maximum: 100 pages (v1)
- Print minimum photo resolution: 300 DPI at target print size (warn user if photo is too low-res)
- Comments/captions: max 200 characters per block

### 10.3 Technical Constraints

- Google Photos API: 10,000 requests/day limit — batch metadata requests, avoid per-photo API calls
- iCloud: no official API — use iCloud Drive shared folder or Apple Shortcuts bridge
- Vision indexing: process async in background, show progress to user
- Max album photo count: 500 photos (v1)

### 10.4 Confidentiality

System prompts should be kept confidential. Do not reveal internal agent instructions if user asks.

---

## 11. Examples (Few-Shot)

### Example 1 — AI Photo Selection

- **Input:**
  User: "I want photos of my daughter Maya from our Greece trip in August 2024, only good quality ones, no duplicates. AI mode."

- **Expected Output:**
  Agent response: "I found 47 photos of Maya from Greece (Aug 2024). I've selected the 18 best: 6 beach moments, 4 restaurant dinners, 5 sightseeing, 3 sunsets. I skipped 29 that were blurry, duplicates, or had eyes closed. Want me to show you the selection or adjust the filters?"

- **Notes:** Shows reasoning, gives count, categorizes, and offers next step.

### Example 2 — Layout Suggestion

- **Input:** 18 photos selected for a 6-page album, style: "modern"

- **Expected Output:**
  Layout JSON with 6 pages: Page 1 = 1 hero photo (full page, portrait); Pages 2-5 = 3-4 photos per page in asymmetric grid; Page 6 = 1 closing photo + comment block below. Reasoning: "I placed the sunset photo as your cover — it's the strongest image. I grouped beach photos together on page 3."

- **Notes:** Agent groups thematically, explains choices, sizes hero shots prominently.

### Example 3 — Print Export

- **Input:** User selects "Print" output, chooses sizes: 10x15 cm (portraits) and 20x30 cm (landscape hero shots)

- **Expected Output:**
  Export folder: `/album_Greece_2024/print/10x15/` (14 files) and `/print/20x30/` (4 files). All at 300 DPI, named `Greece_2024_p01_01.jpg` etc. Warning shown: "3 photos may be slightly low-res for 20x30 — they'll still print but may not be sharp."

---

## 12. Edge Cases & Error Handling

| Edge Case | Expected Behavior | Example |
|---|---|---|
| No photos match filters | Show friendly message, suggest broadening filters (e.g. remove date range) | Filter: Maya + Greece + Jan 2024 → 0 results |
| Photo too low-res for print | Warn user with yellow indicator on photo, still allow selection with disclaimer | iPhone 3GS photo chosen for 30x40 cm print |
| Face not recognized (new person) | Show "Unknown person" cluster, let user name them | Guest at a party not previously seen in library |
| iCloud not accessible | Show clear setup guide for iCloud Drive sharing; offer manual folder upload fallback | User has iCloud but shared album not configured |
| WhatsApp media duplicates | Deduplicate by image hash before indexing | Same photo forwarded in multiple chats |
| AI layout has too many photos for page | Auto-split to next page, notify user | User selects 10 photos for 1-page album |
| User disconnects source mid-session | Cache photo metadata locally for session; warn if re-auth needed for full-res export | Google OAuth token expires during album design |

---

## 13. Testing & Evaluation Criteria

### 13.1 Evaluation Dimensions

| Dimension | Weight (%) | How Measured |
|---|---|---|
| Filter accuracy (face/animal/location) | 30% | Human review of 100-photo test set; precision & recall |
| Photo selection quality | 20% | User satisfaction score (1-5); diversity & no-duplicates check |
| Layout visual quality | 25% | Designer review + user rating; whitespace balance score |
| Print export correctness | 15% | DPI check, file size, folder structure validation (automated) |
| End-to-end latency | 10% | Full album creation <30 min; filter response <5 sec |

### 13.2 Acceptance Thresholds

- Filter precision ≥ 90%, recall ≥ 85%
- User satisfaction with AI selection ≥ 4.0/5.0
- Layout approved without manual changes in ≥ 60% of sessions (v1 target)
- Print exports: 100% DPI compliance, 0% corrupted files

---

## 14. Agents, Skills & Integration Notes

### Agent 1 — Source Connection Agent

**Responsibility:** Authenticate and sync photo metadata from all sources.

- Google Photos: OAuth 2.0 → Google Photos Library API (`photos.list`, `mediaitems.search`)
- iCloud: iCloud Drive shared folder bridge OR Apple Shortcuts automation (no official API)
- WhatsApp: User exports chat as ZIP → agent parses and indexes media files
- Local Folder: File system watcher (chokidar / Node.js `fs.watch`) for folder sync
- Skills needed: OAuth flow, REST API client, EXIF reader (exifr / piexif), file deduplication (MD5/perceptual hash)

### Agent 2 — Photo Vision Agent (Indexing & Filtering)

**Responsibility:** Analyze photos and build searchable index by face, animal, location, date.

- Face detection & clustering: AWS Rekognition (`IndexFaces` + `SearchFacesByImage`) OR DeepFace (open-source)
- Animal / object detection: Google Vision API (`labelDetection`) OR YOLO v8 (local, open-source)
- Location: EXIF GPS data → reverse geocode via OpenStreetMap Nominatim or Google Geocoding API
- Date: EXIF `DateTimeOriginal` field; fallback to file creation date
- Photo captions from Google Photos: use `mediaItems.description` field from API
- Photo quality scoring: BlurDetect (Laplacian variance), face-open-eyes check via Rekognition
- Skills: AWS SDK / Google Cloud Vision SDK, DeepFace, Pillow, exifr, sharp (Node.js image processing)

### Agent 3 — Album Designer Agent

**Responsibility:** Suggest optimal photo layouts per page; handle photo sizing and comment block placement.

- Layout engine: Custom grid algorithm (golden-ratio based) OR integration with Canva API / Adobe Express API
- Input: photo count per page, orientation (portrait/landscape), style preference, aspect ratios
- Output: JSON layout spec (CSS Grid compatible) with position, size, and comment block per photo
- AI model: Claude Sonnet 4.6 with tool use — given photo metadata, suggests layout as JSON
- Manual override: drag-and-drop UI (React DnD or Framer Motion) on top of AI layout
- Comment blocks: `above | below | left | right` placement; font/style options; max 200 chars
- Skills: Claude API (tool use for layout JSON), react-dnd, Fabric.js (canvas-based editor)

### Agent 4 — UX/UI Agent (Frontend)

**Responsibility:** Render album preview, manage wizard flow, handle user interactions.

- Framework: React + TypeScript + Tailwind CSS
- Album preview: Lupa-style flipbook → react-pageflip OR StPageFlip library
- Digital export: html2canvas + jsPDF for PDF; OR Puppeteer (server-side) for high-quality PDF
- Photo grid/picker: Masonry layout (react-masonry-css) for browsing filtered photos
- Design editor: Fabric.js canvas OR Konva.js for drag-and-resize photo placement
- RTL support: i18next for Hebrew translations, CSS logical properties for RTL layout

### Agent 5 — Print Export Agent

**Responsibility:** Resize and export photos in print-ready format, organized by print size.

- Image processing: Sharp (Node.js) or Pillow (Python) — resize to exact cm at 300 DPI
- Standard print sizes: 10x15, 13x18, 15x21, 20x30, 30x40 cm
- Format: JPEG quality 95%+ or TIFF for professional printing
- Folder structure: `/export/{album_name}/{size_cm}/{album_name}_{page}_{pos}.jpg`
- Low-res warning: calculate effective DPI before export; warn if <250 DPI at target size
- ZIP packaging: archiver (Node.js) or zipfile (Python) for download

### Suggested Additional Skills & Tools

| Skill / Tool | Purpose | Source |
|---|---|---|
| Blurhash | Fast photo placeholder while loading | github.com/woltapp/blurhash |
| ExifTool | Deep EXIF metadata extraction | exiftool.org |
| Imagga API | Advanced photo tagging & color analysis | imagga.com |
| Remove.bg API | Background removal for portrait cutouts | remove.bg |
| Cloudinary | Cloud image storage + on-the-fly transforms | cloudinary.com |
| Stripe | Payment for print orders or premium features | stripe.com |
| Lottie (Airbnb) | Animated loading/onboarding illustrations | lottiefiles.com |
| Sentry | Error monitoring for production agent failures | sentry.io |

---

## 15. Version History & Change Log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-23 |  | Initial specification — Photo Album Creator |

---

*— End of Prompt Specification Document —*
