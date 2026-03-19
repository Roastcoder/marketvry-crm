"""
Shared helpers and logger for Horilla Mail views.
"""

import base64
import logging
import re

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


def parse_email_pills_context(email_string, field_type):
    """
    Helper function to parse email strings into pills context
    """
    email_list = []
    if email_string:
        email_list = [e.strip() for e in email_string.split(",") if e.strip()]

    return {
        "email_list": email_list,
        "email_string": email_string or "",
        "field_type": field_type,
        "current_search": "",
    }


def extract_inline_images_with_cid(html_content):
    """Extract base64 inline images and replace with CID references."""
    if not html_content:
        return html_content, []

    inline_images = []
    img_pattern = (
        r'<img([^>]*)src=["\']data:image/([^;]+);base64,([^"\']+)["\']([^>]*)>'
    )

    def replace_img(match):
        before_src = match.group(1)
        image_format = match.group(2)
        base64_data = match.group(3)
        after_src = match.group(4)

        try:
            image_data = base64.b64decode(base64_data)
            cid = f"inline_image_{len(inline_images) + 1}"
            filename = f"{cid}.{image_format}"
            content_file = ContentFile(image_data, name=filename)
            inline_images.append((content_file, cid))
            return f'<img{before_src}src="cid:{cid}"{after_src}>'
        except Exception as e:
            logger.error("Error processing inline image: %s", e)
            return match.group(0)

    cleaned_html = re.sub(img_pattern, replace_img, html_content, flags=re.IGNORECASE)
    return cleaned_html, inline_images
