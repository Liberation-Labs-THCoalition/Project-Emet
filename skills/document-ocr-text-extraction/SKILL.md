---
name: document-ocr-text-extraction
description: "Comprehensive PDF and document processing for government records. Extracts text from PDFs and scanned documents, recognizes tables and forms, performs OCR, and structures unstructured documents. Use this skill when processing government PDFs, extracting data from scanned records, or analyzing document metadata."
---

# Document OCR & Text Extraction Skill

## Overview
Comprehensive capability for extracting structured information from PDFs, scanned documents, images, and complex document formats commonly found in government transparency work.

## Core Capabilities

### Text Extraction
- PDF text extraction with layout preservation
- OCR processing for scanned documents
- Image-based text recognition
- Handwriting recognition (limited)
- Multi-language text extraction

### Structure Recognition
- Table detection and extraction
- Form field identification
- Header and section recognition
- Signature and stamp detection
- Document classification

### Metadata Analysis
- Document creation/modification dates
- Author and software information
- Document properties and tags
- Version history extraction
- Digital signature verification

## Technical Implementation

### Required Libraries
```python
import PyPDF2
import pdfplumber
import pytesseract
import cv2
import PIL
import pandas as pd
import tabula
import camelot
import fitz  # PyMuPDF
```

### Core Functions
```python
def extract_pdf_text(pdf_path, preserve_layout=True):
    """Extract text while maintaining document structure"""
    
def perform_ocr(image_path, language='eng'):
    """OCR processing with preprocessing optimization"""
    
def extract_tables(document_path, pages='all'):
    """Extract structured tables from documents"""
    
def extract_metadata(document_path):
    """Retrieve comprehensive document metadata"""
    
def classify_document_type(content, metadata):
    """Identify document category and structure"""
```

### Image Preprocessing
```python
def preprocess_image_for_ocr(image):
    """Optimize image for OCR accuracy"""
    # Noise reduction
    # Contrast enhancement  
    # Deskewing
    # Binarization
    
def enhance_document_quality(image_path):
    """Improve document readability"""
```

## Document Type Specialization

### Government Forms
- Form 700 financial disclosures
- Campaign finance reports
- Contract documents
- Meeting minutes and agendas
- Public records requests

### Financial Documents
- Bank statements
- Investment portfolios
- Business licenses
- Property records
- Tax documents

### Legal Documents
- Court filings
- Legal contracts
- Regulatory documents
- Compliance reports
- Correspondence

## Data Extraction Patterns

### Structured Data Recognition
```python
def extract_financial_data(document):
    """Extract monetary amounts, dates, entities"""
    
def extract_personal_information(document):
    """Extract names, addresses, contact info"""
    
def extract_dates_and_deadlines(document):
    """Extract temporal information"""
    
def extract_entities_and_organizations(document):
    """Extract organization names and references"""
```

### Relationship Extraction
```python
def identify_document_relationships(documents):
    """Find connections between documents"""
    
def extract_reference_networks(document_set):
    """Map citation and reference patterns"""
```

## Quality Assurance

### Accuracy Validation
- Confidence scoring for extracted text
- Manual verification sampling
- Cross-validation against multiple methods
- Error pattern identification
- Accuracy benchmarking

### Error Handling
```python
def handle_corrupted_files(file_path):
    """Graceful handling of damaged documents"""
    
def validate_extraction_quality(original, extracted):
    """Assess extraction accuracy"""
    
def flag_low_confidence_extractions(results):
    """Identify extractions needing manual review"""
```

## Output Standardization

### Structured Data Format
```json
{
  "document_id": "unique_identifier",
  "source_file": "path/to/original",
  "extraction_metadata": {
    "method": "ocr|pdf_extraction|hybrid",
    "confidence_score": 0.95,
    "processing_date": "timestamp",
    "pages_processed": 12
  },
  "content": {
    "full_text": "complete_extracted_text",
    "structured_data": {
      "tables": [],
      "forms": {},
      "entities": [],
      "dates": [],
      "amounts": []
    }
  },
  "document_metadata": {
    "creation_date": "timestamp",
    "author": "string",
    "file_size": "bytes",
    "page_count": 12
  }
}
```

### Integration Formats
- Database-ready structured data
- Search engine indexable text
- Network analysis relationship data
- Temporal analysis date series
- Financial analysis monetary data

## Performance Optimization

### Processing Efficiency
- Batch processing capabilities
- Parallel document processing
- Memory optimization for large files
- Progress tracking and resumption
- Priority queuing for urgent documents

### Storage Management
- Compressed text storage
- Deduplicated content handling
- Archival and retention policies
- Version control for extractions
- Cache management for repeated access

## Security & Privacy

### Data Protection
- Sensitive information redaction
- Encrypted storage of extracted data
- Access logging and audit trails
- Secure deletion of temporary files
- Privacy-preserving extraction modes

### Compliance Features
```python
def redact_personal_information(text, redaction_level='full'):
    """Remove or mask sensitive personal data"""
    
def apply_retention_policy(document_age, policy):
    """Enforce data retention requirements"""
    
def create_audit_trail(processing_actions):
    """Log all document processing activities"""
```

## Advanced Features

### AI-Enhanced Processing
- Document classification models
- Named entity recognition
- Sentiment analysis of content
- Key phrase extraction
- Document summarization

### Specialized Extractors
```python
def extract_campaign_finance_data(form):
    """Specialized extraction for FEC forms"""
    
def extract_property_records(document):
    """Extract real estate transaction data"""
    
def extract_meeting_minutes(document):
    """Structure meeting discussion and votes"""
```

## Integration Points

### Database Integration
- Direct insertion to PostgreSQL
- Neo4j relationship creation
- Document store indexing
- Search engine preparation
- API endpoint data provision

### Workflow Integration
- Automated processing triggers
- Quality assurance checkpoints
- Manual review queuing
- Error notification systems
- Progress reporting dashboards

## Monitoring & Analytics

### Processing Metrics
- Documents processed per hour
- Extraction accuracy rates
- Error frequency by document type
- Processing time by file size
- Resource utilization tracking

### Quality Metrics
- OCR confidence distributions
- Manual correction frequency
- False positive/negative rates
- User satisfaction scores
- Extraction completeness ratios
