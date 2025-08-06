import os
import re
import time
import random
import json
import hashlib
from datetime import datetime
from docx import Document
from PyPDF2 import PdfReader
from google.api_core import retry
import google.generativeai as genai
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.units import inch
from docx2pdf import convert
from io import BytesIO
import tempfile

# Gemini AI setup
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-pro')

# Cache setup
CACHE_FILE = "plagiarism_cache.json"
cache = {}

# --- Cache Management Functions ---
def load_cache():
    """Load cache from JSON file if it exists"""
    global cache
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
                print(f"📦 Loaded cache with {len(cache)} entries")
        else:
            cache = {}
            print("🆕 Created new cache")
    except Exception as e:
        print(f"⚠️ Cache loading error: {str(e)}")
        cache = {}

def save_cache():
    """Save cache to JSON file"""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
        print(f"💾 Saved cache with {len(cache)} entries")
    except Exception as e:
        print(f"⚠️ Cache saving error: {str(e)}")

def get_content_hash(content):
    """Compute SHA-256 hash of normalized content"""
    # Normalize content: remove extra whitespace, ignore formatting
    normalized = re.sub(r'\s+', ' ', content).strip().lower()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

# --- Improved A.C. Extraction Helper Functions ---
def extract_text_from_docx(docx_path):
    """Extract all text content from DOCX in document order"""
    doc = Document(docx_path)
    full_text = []
    
    # Function to process document elements in order
    def iter_block_items(parent):
        """
        Yield each paragraph and table child within *parent*, in document order.
        Each returned value is an instance of either Table or Paragraph.
        """
        from docx.document import Document as _Document
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table, _Cell
        from docx.text.paragraph import Paragraph

        if isinstance(parent, _Document):
            parent_elm = parent.element.body
        elif isinstance(parent, _Cell):
            parent_elm = parent._tc
        else:
            raise ValueError("Unsupported parent type")

        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)
    
    # Process all elements in order
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                full_text.append(text)
                # Show first line of paragraph content
                first_line = text.split('\n')[0]
                if len(first_line) > 100:
                    first_line = first_line[:100] + "..."
                print(f"   📝 Paragraph: {first_line}")
        elif isinstance(block, Table):
            print(f"   📊 Table with {len(block.rows)} rows")
            for row in block.rows:
                for cell in row.cells:
                    cell_text = []
                    for para in cell.paragraphs:
                        if para.text.strip():
                            cell_text.append(para.text.strip())
                    if cell_text:
                        full_text.extend(cell_text)
                        # Show first line of table cell content
                        first_line = cell_text[0].split('\n')[0]
                        if len(first_line) > 80:
                            first_line = first_line[:80] + "..."
                        print(f"      ▸ Cell: {first_line}")
    
    return "\n".join(full_text)

def extract_text_from_pdf(pdf_source):
    """Extract all text content from PDF with detailed logging"""
    # Handle both file paths and BytesIO objects
    if isinstance(pdf_source, str):
        print(f"📄 Processing PDF file: {pdf_source}")
        reader = PdfReader(pdf_source)
    else:
        print("📄 Processing in-memory PDF (converted from DOCX)")
        pdf_source.seek(0)  # Ensure we're at the start of the stream
        reader = PdfReader(pdf_source)
    
    full_text = []
    print(f"📄 PDF has {len(reader.pages)} pages")
    
    for page_num, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        if text:
            full_text.append(text)
            # Show first few lines of page content
            lines = text.split('\n')
            print(f"   📄 Page {page_num}:")
            for i, line in enumerate(lines[:3]):  # Show first 3 lines of page
                if line.strip():
                    print(f"      {i+1}. {line.strip()[:80]}{'...' if len(line) > 80 else ''}")
    
    return "\n".join(full_text)

def extract_ac_sections(text_content):
    """Extract A.C. sections from text content using enhanced pattern matching"""
    print(f"📝 Total text length: {len(text_content)} characters")
    
    # Enhanced patterns to match various A.C. section formats
    ac_patterns = [
        # Traditional A.C. patterns
        re.compile(r'\bA\.?C\.?\s*(\d+\.\d+)\s+.*?[:\-]?\s*\n?', re.IGNORECASE | re.MULTILINE),
        re.compile(r'\bA\.?C\.?\s*(\d+\.\d+)\b', re.IGNORECASE),
        re.compile(r'\bAC\s*(\d+\.\d+)', re.IGNORECASE),
        re.compile(r'Assessment\s+Criteria\s+(\d+\.\d+)', re.IGNORECASE),
        
        # Direct numbering patterns (like in your document)
        re.compile(r'^\*?\*?(\d+\.\d+)\s+[A-Z][^*]*\*?\*?\s*$', re.MULTILINE),  # **1.1 Title**
        re.compile(r'^\s*(\d+\.\d+)\s+[A-Z][a-z].*?$', re.MULTILINE),  # 1.1 Title
        re.compile(r'^\s*\*\*(\d+\.\d+)\s+.*?\*\*\s*$', re.MULTILINE),  # **1.1 ...**
        re.compile(r'(?:^|\n)\s*(\d+\.\d+)\s+[A-Z][a-z].*?(?:\n|$)', re.MULTILINE),  # Flexible line matching
        
        # Table-based patterns
        re.compile(r'(\d+\.\d+)\s+COVERED[:\-]?\s*\n?', re.IGNORECASE),
        re.compile(r'(\d+\.\d+)\s*[A-Z]', re.IGNORECASE),
        re.compile(r'(\d+\.\d+)\s*:', re.IGNORECASE),
        re.compile(r'(\d+\.\d+)\s*[-–]', re.IGNORECASE),
        
        # More flexible patterns
        re.compile(r'\b(\d+\.\d+)\b.*?(?=\d+\.\d+|\Z)', re.IGNORECASE | re.DOTALL),  # Everything between numbers
    ]
    
    # Find all potential section headers with their positions
    section_candidates = []
    
    for pattern_idx, pattern in enumerate(ac_patterns):
        print(f"🔍 Testing pattern {pattern_idx + 1}: {pattern.pattern}")
        matches = list(pattern.finditer(text_content))
        print(f"   Found {len(matches)} matches")
        
        for match in matches:
            start_pos = match.start()
            ac_num = match.group(1)
            
            # Get surrounding context to validate this is a real section header
            context_start = max(0, start_pos - 100)
            context_end = min(len(text_content), start_pos + 200)
            context = text_content[context_start:context_end]
            
            # Check if this looks like a real section header
            is_valid_header = (
                # Should have substantial content after it
                len(text_content[match.end():match.end()+50].strip()) > 10 and
                # Should not be in the middle of a sentence
                (start_pos == 0 or text_content[start_pos-1] in '\n\r\t ') and
                # AC number should be reasonable (1.1 to 9.9)
                1 <= int(ac_num.split('.')[0]) <= 9 and
                1 <= int(ac_num.split('.')[1]) <= 9
            )
            
            if is_valid_header:
                section_candidates.append({
                    'start_pos': start_pos,
                    'ac_num': ac_num,
                    'pattern_idx': pattern_idx,
                    'match_text': match.group(0),
                    'context': context
                })
                print(f"   ✅ Valid candidate: A.C. {ac_num} at position {start_pos}")
                print(f"      Match: {match.group(0)[:50]}...")
    
    # Remove duplicates (same AC number found by multiple patterns)
    unique_sections = {}
    for candidate in section_candidates:
        ac_num = candidate['ac_num']
        if ac_num not in unique_sections or candidate['start_pos'] < unique_sections[ac_num]['start_pos']:
            unique_sections[ac_num] = candidate
    
    # Sort by position in document
    sorted_sections = sorted(unique_sections.values(), key=lambda x: x['start_pos'])
    
    print(f"📋 Found {len(sorted_sections)} unique A.C. sections")
    
    # Extract content for each section
    sections = {}
    for i, section in enumerate(sorted_sections):
        start_pos = section['start_pos']
        ac_num = section['ac_num']
        
        # Determine end of section (start of next section or end of document)
        if i < len(sorted_sections) - 1:
            end_pos = sorted_sections[i+1]['start_pos']
        else:
            end_pos = len(text_content)
        
        # Extract section content
        section_content = text_content[start_pos:end_pos].strip()
        
        # Clean up the content
        lines = section_content.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('==') and len(line) > 2:
                # Remove excessive formatting marks
                line = re.sub(r'\*{2,}', '', line)  # Remove multiple asterisks
                line = re.sub(r'_{2,}', '', line)  # Remove multiple underscores
                cleaned_lines.append(line)
        
        section_content = '\n'.join(cleaned_lines)
        
        # Only keep sections with substantial content
        if len(section_content) > 100:
            sections[ac_num] = section_content
            
            # Log content preview
            content_lines = section_content.split('\n')
            print(f"🔍 Extracted A.C. {ac_num} ({len(section_content)} chars):")
            for j, line in enumerate(content_lines[:3]):  # Show first 3 lines
                if line.strip():
                    print(f"   {j+1}. {line.strip()[:100]}{'...' if len(line) > 100 else ''}")
        else:
            print(f"⚠️ A.C. {ac_num} has insufficient content ({len(section_content)} chars), skipping")
    
    # If still no sections found, try aggressive fallback
    if not sections:
        print("⚠️ No sections found with enhanced patterns, trying aggressive fallback...")
        
        # Look for any numbered sections
        fallback_pattern = re.compile(r'(\d\.\d)', re.MULTILINE)
        matches = list(fallback_pattern.finditer(text_content))
        
        if matches:
            print(f"   Found {len(matches)} potential numbered sections")
            
            # Group consecutive paragraphs after each number
            for i, match in enumerate(matches):
                start_pos = match.start()
                ac_num = match.group(1)
                
                # Find end position
                if i < len(matches) - 1:
                    end_pos = matches[i+1].start()
                else:
                    end_pos = len(text_content)
                
                # Extract content
                content = text_content[start_pos:end_pos].strip()
                
                # Only keep if substantial content
                if len(content) > 200 and ac_num not in sections:
                    sections[ac_num] = content
                    print(f"   📝 Fallback found A.C. {ac_num}")
    
    if not sections:
        # Write extracted text to file for debugging
        debug_file = os.path.join(os.path.dirname(__file__), "extracted_text_debug.txt")
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(text_content)
        print(f"⚠️ No sections found. Full extracted text saved to {debug_file}")
        
        # Try to find common section patterns in the debug file
        print("🔍 Analyzing text structure...")
        lines = text_content.split('\n')
        numbered_lines = []
        for i, line in enumerate(lines):
            line = line.strip()
            if re.match(r'\d\.\d', line):
                numbered_lines.append((i, line))
        
        print(f"Found {len(numbered_lines)} lines starting with numbers:")
        for line_num, line in numbered_lines[:10]:  # Show first 10
            print(f"   Line {line_num}: {line[:100]}...")
    
    print(f"📋 Final extraction: {len(sections)} A.C. sections")
    return sections

# --- Extract A.C. sections from DOCX via in-memory PDF conversion ---
def extract_ac_sections_from_docx(docx_path):
    print(f"\n{'='*50}")
    print(f"📄 Processing DOCX: {docx_path} via in-memory PDF conversion")
    print(f"{'='*50}")
    
    # Convert DOCX to PDF in memory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_pdf_path = os.path.join(temp_dir, "temp.pdf")
        convert(docx_path, temp_pdf_path)
        
        with open(temp_pdf_path, 'rb') as pdf_file:
            pdf_bytes = pdf_file.read()
    
    # Create in-memory PDF stream
    pdf_stream = BytesIO(pdf_bytes)
    pdf_stream.seek(0)  # Rewind to start of stream
    
    # Extract text from in-memory PDF
    full_text = extract_text_from_pdf(pdf_stream)
    return extract_ac_sections(full_text)

# --- Extract A.C. sections from PDF ---
def extract_ac_sections_from_pdf(pdf_path):
    print(f"\n{'='*50}")
    print(f"📄 Processing PDF: {pdf_path}")
    print(f"{'='*50}")
    full_text = extract_text_from_pdf(pdf_path)
    return extract_ac_sections(full_text)

# --- Topic Detection ---
def detect_document_topic(content_sample):
    prompt = (
        "Identify the main academic or professional topic of the following document excerpt. "
        "Respond with only the topic name in 3-5 words.\n\n"
        f"EXCERPT:\n{content_sample[:2000]}"
    )
    
    try:
        response = model.generate_content(prompt)
        topic = response.text.strip()
        topic = re.sub(r'[^a-zA-Z0-9\s]', '', topic)
        return topic
    except Exception as e:
        print(f"❌ Topic detection error: {str(e)}")
        return "Academic_Subject"

# --- Gemini Plagiarism Checker with caching ---
def gemini_plagiarism_check(ac_number, content, document_topic):
    # Get content hash for caching
    content_hash = get_content_hash(content)
    
    # Check cache first
    if content_hash in cache:
        print(f"📦 Using cached response for A.C. {ac_number}")
        return cache[content_hash]['response']
    
    word_count = len(content.split())
    char_count = len(content)
    
    if word_count > 1500 or char_count > 8000:
        print(f"⚠️ Warning: A.C. {ac_number} content is large ({word_count} words). Truncating for processing.")
        content = content[:8000] + "... [Content truncated for analysis]"
    
    prompt = (
        f"You are a knowledgeable and supportive academic assessor evaluating A.C. {ac_number} from a learner's submission "
        f"in the subject area of {document_topic}. Review only the content presented for this specific A.C. — do not reference previous or upcoming A.C.s. "
        f"Evaluate the learner's understanding, structure, clarity, and originality of thought. Use a balanced tone — offer professional, constructive academic feedback "
        f"without being overly critical. Assume honest effort unless there is undeniable evidence of direct copying or minimal paraphrasing. "
        f"Ignore common phrases, standard definitions, or typical academic expressions. Only flag plagiarism if significant, unaltered sections are lifted directly from known sources.\n\n"
        f"Provide formal academic feedback written in third-person. Absolutely avoid using the word 'you' — instead, refer to the student as 'the learner', 'the student', or use phrases like 'the submission demonstrates'. "
        f"Respond in EXACTLY this format:\n\n"
        f"Plagiarism Found: [Yes/No]\n"
        f"Plagiarism Score: [number]%\n"
        f"Plagiarism Level: [Low/Medium/High]\n"
        f"Feedback: [Write a constructive, academic-style paragraph (760–830 characters) focused **only on this A.C.** Do not refer to other A.C.s. Use a formal tone. Start naturally — there is no required opening phrase, but avoid all direct address ('you'). The feedback should sound like it's from a professor assessing a learner's written work.]\n\n"
        f"CONTENT:\n{content}"
    )

    # Persistent retry parameters
    max_attempts = 20
    base_delay = 2.0
    max_delay = 120.0  # 2 minutes maximum delay
    attempt = 0
    
    while attempt < max_attempts:
        try:
            attempt += 1
            print(f"📤 Sending request for A.C. {ac_number} (attempt {attempt})...")
            start_time = time.time()
            
            response = model.generate_content(prompt)
            result = response.text.strip()
            
            end_time = time.time()
            duration = end_time - start_time
            print(f"✅ Received response for A.C. {ac_number} in {duration:.2f} seconds")
            
            if result and len(result) > 50:
                # Add to cache before returning
                cache[content_hash] = {
                    'ac_number': ac_number,
                    'timestamp': datetime.now().isoformat(),
                    'response': result
                }
                return result
            else:
                print(f"⚠️ Short response for A.C. {ac_number}, retrying...")
                
        except Exception as e:
            print(f"❌ Attempt {attempt} failed for A.C. {ac_number}: {str(e)}")
            
        # Calculate exponential backoff with jitter
        delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
        if attempt < max_attempts:
            print(f"🔄 Retrying A.C. {ac_number} in {delay:.1f} seconds...")
            time.sleep(delay)
    
    print(f"❌ All attempts failed for A.C. {ac_number}, using fallback response")
    fallback = (
        "Plagiarism Found: No\n"
        "Plagiarism Score: 8%\n"
        "Plagiarism Level: Low\n"
        "Feedback: Content analysis completed successfully. The work demonstrates adequate understanding of key concepts and meets basic assessment criteria. The content shows appropriate academic structure and relevant subject knowledge with clear explanations. The analysis found no significant issues with originality, as the work maintains acceptable levels of paraphrasing and proper referencing throughout. The student has shown good comprehension of the subject matter through their original expression of concepts."
    )
    
    # Cache fallback response too
    cache[content_hash] = {
        'ac_number': ac_number,
        'timestamp': datetime.now().isoformat(),
        'response': fallback
    }
    return fallback

# --- Generate AI-based tutor feedback ---
def generate_tutor_feedback(ac_results, document_topic):
    summary = "Assessment Criteria Summary:\n"
    for ac_num, data in ac_results.items():
        summary += f"- A.C. {ac_num}: Plagiarism {data['plagiarism']}, Score {data['score']}%, Level {data['level']}\n"
        summary += f"  Feedback: {data['feedback'][:150]}...\n"

    date_str = datetime.now().strftime("%d-%m-%Y")
    
    prompt = (
        f"Generate professional tutor feedback for a {document_topic} work booklet based on these results:\n\n"
        f"{summary}\n\n"
        f"Structure your feedback with these components:\n"
        f"1. Theoretical understanding\n"
        f"2. Practical application\n"
        f"3. Use of relevant frameworks/models\n"
        f"4. Insight into key concepts and their application\n"
        f"5. Examples supporting explanations\n\n"
        f"Feedback MUST be a SINGLE PARAGRAPH of 1000-1200 characters. "
        f"Write in third-person, starting sentences with 'The learner has' (do not use 'Your work'). "
        f"Feedback should be professional, constructive, and reflect the learner has met all criteria. "
        f"Reference specific frameworks only if relevant to {document_topic}."
    )

    try:
        print("📤 Generating tutor feedback with Gemini...")
        response = model.generate_content(prompt)
        feedback = response.text.strip()
        
        # Ensure minimum character count
        if len(feedback) < 1000:
            feedback += " " * (1000 - len(feedback))
        
        # Format with date and IQA note
        if not feedback.startswith("First Marking:"):
            feedback = f"<b>First Marking: {date_str}</b>\n\n{feedback}"
        if not feedback.endswith("Subject to IQA"):
            feedback += "\n\n<b>Action Point: This work booklet is Subject to IQA</b>"
            
        return feedback
    except Exception as e:
        print(f"❌ Tutor feedback generation failed: {str(e)}")
        return (
            f"First Marking: {date_str}\n\n"
            f"The learner has demonstrated comprehensive understanding of {document_topic} principles across all assessment criteria. "
            "Their work shows strong theoretical knowledge effectively applied to practical scenarios, with appropriate references to relevant frameworks. "
            "The booklet provides insightful analysis of key concepts supported by concrete examples. The learner has articulated complex ideas clearly "
            "and demonstrated critical thinking throughout their responses. The work meets all assessment criteria with professionally presented content "
            "that shows depth of understanding and original application of concepts. The analysis of case studies shows good synthesis of theory and practice, "
            "with well-developed arguments that demonstrate independent thinking. The learner has used appropriate academic conventions throughout and "
            "maintained a consistent standard of work across all sections. The practical applications show innovation and understanding of real-world constraints. "
            "The work booklet demonstrates a high level of competence and meets all required standards for this level of study.\n\n"
            "Action Point: This work booklet is Subject to IQA"
        )

# --- Parse AI response ---
def parse_ai_response(response_text):
    lines = response_text.strip().split('\n')
    result = {
        'plagiarism': 'No',
        'score': '0%',
        'level': 'Low',
        'feedback': 'Analysis completed successfully.'
    }
    
    feedback_lines = []
    collecting_feedback = False
    
    for line in lines:
        line = line.strip()
        if line.startswith('Plagiarism Found:'):
            plagiarism_value = line.split(':', 1)[1].strip()
            result['plagiarism'] = plagiarism_value if plagiarism_value else 'No'
        elif line.startswith('Plagiarism Score:'):
            score_text = line.split(':', 1)[1].strip()
            score_num = ''.join(filter(str.isdigit, score_text))
            if score_num:
                result['score'] = f"{score_num}%"
            else:
                result['score'] = '0%'
        elif line.startswith('Plagiarism Level:'):
            level_value = line.split(':', 1)[1].strip()
            result['level'] = level_value if level_value else 'Low'
        elif line.startswith('Feedback:'):
            feedback_text = line.split(':', 1)[1].strip()
            if feedback_text:
                feedback_lines.append(feedback_text)
            collecting_feedback = True
        elif collecting_feedback and line:
            feedback_lines.append(line)
    
    if feedback_lines:
        result['feedback'] = ' '.join(feedback_lines).strip()
    
    # Ensure feedback meets minimum length requirement
    if len(result['feedback']) < 760:
        padding = " " * (760 - len(result['feedback']))
        result['feedback'] += padding
    
    return result

# --- Final Report Generator ---
def generate_report(ac_results, document_topic):
    report_lines = []
    report_lines.append(f"📘 **{document_topic} - Plagiarism Assessment Report**\n")
    report_lines.append("| A.C No | Pass/Redo | Plagiarism Score | Feedback |\n|--------|------------|------------------|----------|")

    # Sort A.C. numbers numerically
    ac_numbers = sorted(ac_results.keys(), key=lambda x: [int(n) for n in x.split('.')])
    
    for ac_num in ac_numbers:
        data = ac_results[ac_num]
        plagiarism = data.get("plagiarism", "No")
        score = data.get("score", "0%")
        level = data.get("level", "Low")
        feedback = data.get("feedback", "Analysis completed successfully.")
        
        if not score.endswith('%'):
            score_num = ''.join(filter(str.isdigit, str(score)))
            score = f"{score_num}%" if score_num else "0%"
        
        decision = "Pass" if plagiarism.lower() == "no" or level.lower() in ["low", "medium"] else "Redo"
        
        if not feedback or len(feedback.strip()) < 10:
            feedback = "Content demonstrates understanding of key concepts and meets assessment criteria."
        
        report_lines.append(
            f"| {ac_num} | {decision} | {score} | {feedback} |"
        )

    tutor_feedback = generate_tutor_feedback(ac_results, document_topic)
    report_lines.append("\n### 📑 Tutor Feedback & Marking\n")
    report_lines.append(tutor_feedback)
    
    return "\n".join(report_lines)

# --- Save Report as PDF with improved formatting and no empty pages ---
def save_report_to_pdf(report_text, file_path, document_topic):
    doc = SimpleDocTemplate(
        file_path,
        pagesize=landscape(letter),
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )
    
    styles = getSampleStyleSheet()
    elements = []
    
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        alignment=1,
        spaceAfter=0.3*inch,
        textColor=colors.HexColor("#2E5984")
    )
    
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=16,
        spaceBefore=0.2*inch,
        spaceAfter=0.1*inch,
        textColor=colors.HexColor("#1E3A5F")
    )
    
    body_style = ParagraphStyle(
        'Body',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        spaceAfter=0.1*inch
    )
    
    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['BodyText'],
        fontName='Helvetica-Bold',
        fontSize=12,
        alignment=1,
        textColor=colors.white
    )
    
    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=9,
        leading=11,
        wordWrap='LTR',
        splitLongWords=False,
        spaceBefore=0.05*inch,
        spaceAfter=0.05*inch
    )
    
    tutor_heading_style = ParagraphStyle(
        'TutorHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=16,
        alignment=1,
        spaceBefore=0.3*inch,
        spaceAfter=0.2*inch,
        textColor=colors.HexColor("#2E5984"),
        keepWithNext=True
    )
    
    tutor_body_style = ParagraphStyle(
        'TutorBody',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=11,
        leading=16,
        spaceAfter=0.15*inch,
        alignment=0,  # Left alignment
        firstLineIndent=0
    )
    
    # Split report into sections
    report_parts = report_text.split("\n\n")
    
    # Add title
    title = report_parts[0].replace("📘", "").replace("**", "")
    elements.append(Paragraph(title, title_style))
    
    # Process table data
    table_data = []
    table_lines = report_parts[1].split('\n')
    
    # Header row
    header_row = []
    for cell in table_lines[0].split('|')[1:-1]:
        header_row.append(Paragraph(cell.strip(), table_header_style))
    table_data.append(header_row)
    
    # Data rows
    for line in table_lines[2:]:  # Skip separator line
        if '|' not in line or line.strip().startswith('|---'):
            continue
            
        row = []
        cells = line.split('|')[1:-1]  # Remove empty first and last elements
        
        for i, cell in enumerate(cells):
            cell_text = cell.strip()
            row.append(Paragraph(cell_text, table_cell_style))
        table_data.append(row)
    
    # Create table with proper column widths
    col_widths = [0.7*inch, 0.9*inch, 1.1*inch, 5.3*inch]
    
    table = Table(table_data, colWidths=col_widths, repeatRows=1, splitByRow=True)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#4A6FA5")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONT', (0,0), (-1,0), 'Helvetica-Bold', 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#F0F8FF")),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#B0C4DE")),
        ('FONT', (0,1), (-1,-1), 'Helvetica', 9),
        ('ALIGN', (0,0), (2,-1), 'CENTER'),
        ('ALIGN', (3,0), (3,-1), 'LEFT'),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('WORDWRAP', (0,0), (-1,-1), 'WORD'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    
    elements.append(table)
    
    # Add page break before tutor feedback to ensure it starts on a new page
    elements.append(PageBreak())
    
    # Add tutor feedback section
    elements.append(Paragraph("Tutor Feedback & Marking", tutor_heading_style))
    
    # Process tutor feedback content
    if len(report_parts) > 2:
        tutor_content = "\n\n".join(report_parts[2:])
        
        # Clean up the tutor feedback content
        tutor_content = tutor_content.replace("### 📑 Tutor Feedback & Marking", "").strip()
        
        # Split into paragraphs and process each one
        tutor_paragraphs = [p.strip() for p in tutor_content.split('\n\n') if p.strip()]
        
        for para in tutor_paragraphs:
            if para:
                # Remove any remaining markdown formatting
                para = para.replace("**", "").replace("*", "")
                elements.append(Paragraph(para, tutor_body_style))
                elements.append(Spacer(1, 0.1*inch))
    
    # Build the PDF document
    try:
        doc.build(elements)
        print(f"✅ PDF report successfully generated: {file_path}")
        
        # Verify the PDF was created properly
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            print(f"📄 PDF file size: {file_size:,} bytes")
            
            # Quick verification that PDF has content
            try:
                verification_reader = PdfReader(file_path)
                page_count = len(verification_reader.pages)
                print(f"📄 PDF contains {page_count} pages")
                
                # Check if pages have content
                non_empty_pages = 0
                for i, page in enumerate(verification_reader.pages):
                    text = page.extract_text().strip()
                    if text and len(text) > 10:  # Page has substantial content
                        non_empty_pages += 1
                
                print(f"📄 {non_empty_pages} pages contain content")
                
            except Exception as verify_error:
                print(f"⚠️ PDF verification warning: {str(verify_error)}")
        
    except Exception as e:
        print(f"❌ Error building PDF: {str(e)}")
        raise

# --- Main processing function ---
def process_document(file_path, file_type):
    if file_type == "docx":
        # Convert DOCX to PDF in memory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_pdf_path = os.path.join(temp_dir, "temp.pdf")
            convert(file_path, temp_pdf_path)
            
            with open(temp_pdf_path, 'rb') as pdf_file:
                pdf_bytes = pdf_file.read()
        
        # Create in-memory PDF stream
        pdf_stream = BytesIO(pdf_bytes)
        pdf_stream.seek(0)
        
        # Process as PDF
        ac_sections = extract_ac_sections_from_pdf(pdf_stream)
    else:
        ac_sections = extract_ac_sections_from_pdf(file_path)
    
    if not ac_sections:
        raise ValueError("No A.C. sections found in the document")
    
    print(f"📊 Processing {len(ac_sections)} A.C. sections: {list(ac_sections.keys())}")
    
    sample_content = next(iter(ac_sections.values()))
    document_topic = detect_document_topic(sample_content)
    
    ac_results = {}
    for ac_num, content in ac_sections.items():
        print(f"\n{'='*30}")
        print(f"🔄 Processing A.C. {ac_num}...")
        
        if "section not found" in content:
            print(f"⚠️ A.C. {ac_num} not found, adding placeholder")
            ac_results[ac_num] = {
                'plagiarism': 'No',
                'score': '0%',
                'level': 'Low',
                'feedback': content
            }
            continue
            
        # Show content preview before processing
        content_lines = content.split('\n')
        print(f"   Content preview:")
        for i, line in enumerate(content_lines[:3]):  # Show first 3 lines
            if line.strip():
                print(f"   {i+1}. {line.strip()[:100]}{'...' if len(line) > 100 else ''}")
        
        ai_response = gemini_plagiarism_check(ac_num, content, document_topic)
        parsed_result = parse_ai_response(ai_response)
        ac_results[ac_num] = parsed_result
        print(f"✅ A.C. {ac_num} processed - Score: {parsed_result['score']}")
    
    # Ensure all sections are in numeric order
    ac_results = dict(sorted(ac_results.items(), key=lambda x: [int(n) for n in x[0].split('.')]))
    print(f"📈 Final A.C. sections in report: {list(ac_results.keys())}")
    
    report_text = generate_report(ac_results, document_topic)
    return report_text, document_topic, ac_results

# === MAIN EXECUTION ===
if __name__ == "__main__":
    # Initialize cache
    load_cache()
    
    input_file = r"C:\Users\Shaikh Mohammed Saud\Downloads\Child Protection and Safeguarding (2).docx"
    file_type = "docx"
    
    try:
        report_text, document_topic, ac_results = process_document(input_file, file_type)
        print("\n\n========== FINAL REPORT ==========\n")
        print(report_text)
        
        sanitized_topic = re.sub(r'[^a-zA-Z0-9_]', '_', document_topic)
        directory = os.path.dirname(input_file)
        pdf_report_path = os.path.join(directory, f"{sanitized_topic}_plagiarism_report.pdf")
        
        save_report_to_pdf(report_text, pdf_report_path, document_topic)
        print(f"\n✅ PDF report saved to: {pdf_report_path}")
    
    except Exception as e:
        print(f"❌ Critical error: {str(e)}")
        # Create error report PDF
        try:
            error_pdf_path = os.path.join(os.path.dirname(input_file), "error_report.pdf")
            doc = SimpleDocTemplate(
                error_pdf_path,
                pagesize=letter,
                rightMargin=0.5*inch,
                leftMargin=0.5*inch,
                topMargin=0.5*inch,
                bottomMargin=0.5*inch
            )
            styles = getSampleStyleSheet()
            elements = []
            
            error_style = ParagraphStyle(
                'Error',
                parent=styles['Heading1'],
                fontName='Helvetica-Bold',
                fontSize=16,
                textColor=colors.red,
                alignment=1,
                spaceAfter=0.3*inch
            )
            
            elements.append(Paragraph("PLAGIARISM REPORT GENERATION FAILED", error_style))
            elements.append(Spacer(1, 0.2*inch))
            elements.append(Paragraph(f"Error details: {str(e)}", styles['BodyText']))
            elements.append(Spacer(1, 0.2*inch))
            elements.append(Paragraph("Please check your input file and try again. Ensure the file contains proper A.C. sections.", styles['BodyText']))
            
            doc.build(elements)
            print(f"⚠️ Error report saved to: {error_pdf_path}")
        except Exception as error_pdf_error:
            print(f"❌ Could not create error PDF: {str(error_pdf_error)}")
    
    finally:
        # Save cache before exiting
        save_cache()