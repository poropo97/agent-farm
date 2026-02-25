"""
agents/content_agent.py

Generates SEO content, marketing copy, blog posts, and social media content.
Focused on affiliate marketing and organic traffic generation.
"""

import logging
import re

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

CONTENT_SYSTEM_PROMPT = """You are an expert content marketer and copywriter for an AI agent farm.
Your goal is to create content that drives traffic and conversions.

Specialties:
- SEO-optimized blog posts and articles
- Product review articles (affiliate marketing)
- Landing page copy
- Email sequences
- Social media posts (Twitter, LinkedIn)
- Product descriptions

Always:
- Write for humans first, search engines second
- Include clear CTAs
- Use natural keyword integration
- Focus on benefits over features
- Match the tone to the target audience
- Output content ready to publish (no placeholders unless specified)"""


class ContentAgent(BaseAgent):
    AGENT_TYPE = "content"
    DEFAULT_LLM_LEVEL = "simple"

    def _default_system_prompt(self) -> str:
        return CONTENT_SYSTEM_PROMPT

    def _execute(self, task: dict) -> dict:
        instructions = task.get("instructions", "")
        instructions_upper = instructions.upper()

        if "SEO_ARTICLE" in instructions_upper or "BLOG_POST" in instructions_upper:
            return self._write_seo_article(task)
        elif "PRODUCT_REVIEW" in instructions_upper:
            return self._write_product_review(task)
        elif "EMAIL_SEQUENCE" in instructions_upper:
            return self._write_email_sequence(task)
        elif "SOCIAL_POSTS" in instructions_upper:
            return self._write_social_posts(task)
        elif "LANDING_COPY" in instructions_upper:
            return self._write_landing_copy(task)
        else:
            return self._general_content(task)

    def _write_seo_article(self, task: dict) -> dict:
        """Write a full SEO-optimized blog article."""
        instructions = task.get("instructions", "")
        prompt = f"""Write a complete SEO-optimized article.

Requirements:
{instructions}

Structure:
- Title (H1) with primary keyword
- Meta description (155 chars)
- Introduction (hook + keyword)
- 4-6 H2 sections with H3 subsections
- FAQ section (3-5 questions)
- Conclusion with CTA
- Word count: 1500-2500 words

Format in Markdown. Make it genuinely helpful and informative."""
        return self._call_llm(prompt, max_tokens=4096, level="simple")

    def _write_product_review(self, task: dict) -> dict:
        """Write an affiliate product review."""
        instructions = task.get("instructions", "")
        prompt = f"""Write a comprehensive affiliate product review.

Product/Details:
{instructions}

Structure:
- Title: "[Product] Review: [Benefit/Year]"
- Quick verdict (pros/cons table)
- Who it's for
- Deep dive into features (be specific)
- Pricing analysis
- Comparison with 2-3 alternatives
- Final verdict + affiliate CTA
- FAQ (3 questions)

Be honest and balanced. Include specific details. Word count: 1200-2000 words. Format in Markdown."""
        return self._call_llm(prompt, max_tokens=4096, level="simple")

    def _write_email_sequence(self, task: dict) -> dict:
        """Write an email welcome/nurture sequence."""
        instructions = task.get("instructions", "")
        prompt = f"""Write a 5-email welcome/nurture sequence.

Context:
{instructions}

For each email:
- Subject line (with A/B variant)
- Preview text
- Body (conversational, 200-400 words)
- CTA

Emails:
1. Welcome + quick win
2. Problem/story
3. Solution introduction
4. Social proof + objection handling
5. Main offer CTA

Format clearly with --- separators between emails."""
        return self._call_llm(prompt, max_tokens=4096, level="simple")

    def _write_social_posts(self, task: dict) -> dict:
        """Write social media posts."""
        instructions = task.get("instructions", "")
        prompt = f"""Write social media posts for:

{instructions}

Create:
- 5 Twitter/X posts (280 chars max each, include hashtags)
- 3 LinkedIn posts (professional tone, 150-300 words each)
- 5 short-form hooks (for TikTok/Reels captions)

Make them varied in style: educational, story, controversial, listicle, question."""
        return self._call_llm(prompt, max_tokens=3000, level="simple")

    def _write_landing_copy(self, task: dict) -> dict:
        """Write landing page copy sections."""
        instructions = task.get("instructions", "")
        prompt = f"""Write complete landing page copy.

Product/Service:
{instructions}

Include:
- Hero: Headline (power word + benefit + specificity) + subheadline + CTA button text
- Social proof section (3 testimonials to create/placeholder)
- Features section (3 features with icons descriptions)
- Benefits section (how life improves)
- Pricing section (1-3 tiers with recommended tier)
- FAQ (5 questions)
- Footer CTA

Use persuasion principles: scarcity, social proof, authority, specificity."""
        return self._call_llm(prompt, max_tokens=4096, level="simple")

    def _general_content(self, task: dict) -> dict:
        """Handle general content tasks."""
        return self._call_llm(
            task.get("instructions", ""),
            max_tokens=3000,
            level="simple",
        )
