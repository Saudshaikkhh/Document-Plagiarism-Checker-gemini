# Plagiarism Detection System

## Overview

This is a Streamlit-based plagiarism detection system that analyzes documents for potential plagiarism using Google's Gemini AI. The application supports multiple file formats (PDF, DOCX, TXT) and provides detailed analysis reports with similarity scores and highlighted text sections. The system features a web-based interface for file uploads, real-time analysis processing, and generates comprehensive reports in both visual and PDF formats.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Streamlit Web Application**: Single-page application built with Streamlit framework
- **Interactive UI Components**: File upload widgets, progress bars, and result visualization
- **Custom CSS Styling**: Enhanced visual presentation with custom styling for upload sections, status boxes, and results display
- **Real-time Feedback**: Progress indicators and status updates during document processing

### Backend Architecture
- **Modular Processing Pipeline**: Core plagiarism detection logic separated into `plagiarism_backend.py`
- **Document Processing Engine**: Multi-format document parser supporting PDF (PyPDF2), DOCX (python-docx), and plain text
- **AI-Powered Analysis**: Integration with Google Gemini 2.5-Pro model for advanced text similarity detection
- **Caching System**: JSON-based caching mechanism to store analysis results and improve performance
- **Report Generation**: PDF report creation using ReportLab with tables, charts, and formatted text

### Data Processing Flow
- **Text Extraction**: Document content extraction with format-specific parsers
- **Content Hashing**: SHA-256 hashing for cache key generation and duplicate detection
- **AI Analysis**: Gemini AI processes text chunks for plagiarism detection with retry mechanisms
- **Result Aggregation**: Compilation of similarity scores, flagged sections, and source attributions

### Visualization and Reporting
- **Plotly Integration**: Interactive charts and graphs for similarity score visualization
- **Pandas DataFrames**: Structured data handling for analysis results
- **PDF Generation**: Professional report creation with tables, styling, and visual elements
- **Real-time Updates**: Live progress tracking during document analysis

## External Dependencies

### AI Services
- **Google Gemini AI**: Primary plagiarism detection engine using Gemini 2.5-Pro model
- **Google AI API**: Requires GEMINI_API_KEY environment variable for authentication

### Document Processing Libraries
- **PyPDF2**: PDF document text extraction
- **python-docx**: Microsoft Word document processing
- **docx2pdf**: Document format conversion capabilities

### Web Framework and UI
- **Streamlit**: Core web application framework
- **Plotly**: Interactive data visualization and charting
- **Pandas**: Data manipulation and analysis

### Report Generation
- **ReportLab**: Professional PDF report creation with advanced formatting
- **BytesIO**: In-memory file handling for document processing

### System Dependencies
- **JSON**: Local caching and data persistence
- **hashlib**: Content hashing for cache management
- **tempfile**: Temporary file handling during processing
- **datetime**: Timestamp management for cache and reports