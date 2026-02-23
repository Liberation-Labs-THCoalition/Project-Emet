---
name: government-portal-navigation  
description: "Specialized automation for navigating government transparency portals including Legistar meeting systems, NextRequest PRA portals, Cal-Access campaign finance, and public records databases. Use this skill when you need to scrape government meetings, automate public records requests, or extract data from official portals."
---

# Government Portal Navigation Skill

## Overview
Specialized capability for navigating and extracting data from government transparency portals, meeting management systems, and public records databases.

## Core Capabilities

### Legistar System Expertise
- Navigate meeting calendars and agenda structures
- Extract voting records and attendance data
- Download meeting minutes, agendas, and supporting documents
- Handle pagination and search functionality
- Parse meeting metadata (date, time, attendees, topics)

### Public Records Portal Navigation
- NextRequest PRA system automation
- Cal-Access campaign finance data extraction
- Secretary of State business filing navigation
- County assessor property database queries
- Municipal permit and licensing systems

### Data Extraction Protocols
- Structured data extraction from HTML tables
- Document link collection and batch downloading
- Metadata preservation during collection
- Error handling for missing or corrupted data
- Rate limiting to avoid overwhelming servers

## Technical Implementation

### Required Libraries
```python
import requests
import BeautifulSoup
import selenium
import pandas as pd
import time
import logging
```

### Core Functions
```python
def navigate_legistar(base_url, jurisdiction):
    """Navigate Legistar meeting management system"""
    
def extract_meeting_data(meeting_url):
    """Extract structured data from meeting pages"""
    
def download_documents(document_links, destination):
    """Batch download meeting documents"""
    
def parse_voting_records(meeting_data):
    """Extract and structure voting information"""
```

### Error Handling Patterns
- Retry logic for network timeouts
- Graceful degradation for missing data
- Logging for failed extractions
- Continuation from interruption points

## Usage Guidelines

### Respectful Scraping
- Implement delays between requests
- Respect robots.txt files
- Use appropriate user agent strings
- Monitor server response times

### Data Validation
- Verify data completeness
- Cross-check against multiple sources
- Flag anomalies for manual review
- Maintain data provenance records

### Legal Compliance
- Only access publicly available information
- Respect terms of service
- Maintain audit trails
- Follow public records laws

## Output Formats

### Structured Data
```json
{
  "meeting_id": "unique_identifier",
  "date": "YYYY-MM-DD",
  "jurisdiction": "government_body",
  "agenda_items": [],
  "voting_records": [],
  "attendees": [],
  "documents": []
}
```

### Integration Points
- Database insertion protocols
- API endpoint specifications
- File naming conventions
- Metadata standards

## Performance Metrics
- Pages successfully navigated per hour
- Data extraction accuracy rate
- Document download completion rate
- Error recovery success rate

## Security Considerations
- No authentication credential storage
- Secure transmission protocols
- Data anonymization where required
- Access logging for accountability
