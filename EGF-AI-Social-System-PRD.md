# Easy Gluten Free
# AI Social Media Automation System
## Product Requirements Document (PRD)

Version: MVP 1.0  
Owner: Easy Gluten Free  
Purpose: Build an AI-powered social media automation system that understands the Easy Gluten Free brand identity and generates Pinterest content aligned with the brand voice.

---

# 1. Logical Layer
(Product Goals, Brand Rules, Strategic Constraints)

## 1.1 Product Vision

Create an AI-powered social media automation system capable of:

- understanding the Easy Gluten Free brand identity
- generating original gluten-free content
- posting Pinterest pins automatically
- driving traffic to the Easy Gluten Free website
- growing the email subscriber list

The system should eventually expand to:

- Instagram
- TikTok
- blog content generation
- digital product promotion

---

## 1.2 Primary Goals (MVP)

Initial goals:

- publish **3 Pinterest pins per day**
- drive users to blog recipe pages
- increase email subscribers
- maintain strong brand consistency

---

## 1.3 Brand Identity

All content must strictly follow the **Brand Knowledge File**.

Core personality:

- witty
- sarcastic (light)
- playful
- empathetic
- relatable

Avoid:

- clinical tone
- influencer hype
- fake enthusiasm
- generic marketing language

---

## 1.4 Content Rules

Recipes must be:

- gluten free
- original
- not duplicated from existing database

Forbidden ingredients:

- alcohol
- pork

Medical content:

- no medical advice unless citing trusted sources
- avoid exaggerated health claims

---

## 1.5 Content Types (MVP)

Primary:

Pinterest recipe pins

Secondary:

- gluten-free cooking tips
- beginner gluten-free education

Future:

- Instagram reels
- TikTok content
- blog articles
- digital products

---

## 1.6 Posting Frequency

Pinterest:

3 pins per day

Future platforms:

Instagram  
TikTok

---

## 1.7 Monetization Strategy

Short term:

Drive traffic to the Easy Gluten Free blog.

Long term:

Monetize through:

- digital products
- gluten-free ebooks
- meal planners
- affiliate kitchen tools

---

# 2. Analytical Layer
(How the system analyzes data and generates ideas)

## 2.1 Data Sources

Reddit communities:

- r/glutenfree
- r/glutenfreebaking
- r/glutenfreecooking
- r/glutenfreerecipes
- r/celiac

Trusted sources:

- national medical journals
- registered dietitian blogs

Internal sources:

Easy Gluten Free website

---

## 2.2 Trend Detection

Trends are detected using:

- engagement levels
- topic frequency
- relevance to gluten-free cooking

Topics must provide **real value to the gluten-free community**.

---

## 2.3 Idea Generation

The system generates **20 content ideas per day**.

Each idea receives a score based on:

- engagement level
- novelty
- SEO potential
- brand alignment

Top **3 ideas** are selected.

---

## 2.4 Recipe Duplication Prevention

The system maintains a **recipe database** tracking:

- recipe title
- cuisine type
- cooking method
- primary ingredients

Recipes cannot duplicate existing ones.

Example:

If the database contains:

Gluten-Free Pancakes

The system must not generate:

- Best Gluten-Free Pancakes
- Easy Gluten-Free Pancakes

Instead generate variations:

- Gluten-Free Banana Pancakes
- Gluten-Free Blueberry Pancakes

---

## 2.5 SEO Strategy

Each pin must include:

- SEO title
- keyword optimized description
- natural keyword usage

Example keywords:

- gluten free pancakes
- easy gluten free dinner
- gluten free baking tips

---

# 3. Computational Layer
(System Architecture and Technology)

## 3.1 Deployment

The system runs locally on the user's laptop.

Goals:

- minimal cost
- full control
- lightweight infrastructure

---

## 3.2 Technology Stack

Language:

Python

Database:

SQLite

Automation:

Custom Python scripts

---

## 3.3 AI Models

Text generation:

- GPT
- Claude

Model chosen dynamically based on lowest cost.

Tasks:

- idea generation
- captions
- SEO titles

---

## 3.4 Image Generation

Image generator:

Nano Banana

Output:

1 image per pin

Image format:

1000x1500 (Pinterest vertical format)

---

## 3.5 Website Integration

Website:

WordPress

Recipe plugin:

WP Recipe Maker

Capabilities:

- read recipe database
- track duplicate recipes
- update recipe metadata

The system crawls the site **daily for new posts**.

---

## 3.6 Database Structure

SQLite database tables:

recipes  
content_ideas  
generated_pins  
posted_pins  
trend_topics  

Example recipe table fields:

- recipe_id
- recipe_title
- cuisine
- cooking_method
- ingredients
- date_created

---

## 3.7 Visual Style

All images follow the **Sunday Light Kitchen** aesthetic.

Key elements:

- sage cabinets
- cream countertops
- wooden shelves
- copper cookware
- natural light

Recipe pins:

food photography style

Tip pins:

infographic style

---

# 4. Procedural Layer
(Operational Workflow)

## 4.1 Daily Pipeline

1. Collect data from Reddit and trusted blogs.
2. Analyze trending topics.
3. Generate 20 content ideas.
4. Score ideas.
5. Select top 3.
6. Generate pin titles and captions.
7. Generate images.
8. Create preview.
9. Send to dashboard for approval.
10. Schedule pins.

---

## 4.2 Scheduling

Pins are scheduled at optimal engagement times.

Initially:

Use standard Pinterest best times.

Later:

Learn from engagement data.

---

## 4.3 Human Approval

Before posting:

User reviews:

- image
- title
- description
- link

Rejected pins regenerate automatically.

---

## 4.4 Error Handling

If:

image generation fails → retry  
duplicate recipe detected → regenerate  
API fails → retry

---

# 5. MVP Definition

The MVP is complete when the system can:

- analyze gluten-free trends
- generate 3 Pinterest pins per day
- generate images automatically
- track recipes
- allow human approval
- schedule posts

---

# 6. Future Expansion

Planned versions:

V2: recipe generation  
V3: Instagram automation  
V4: TikTok automation  
V5: WordPress publishing  
V6: digital product automation