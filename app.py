import streamlit as st
import time
from io import BytesIO
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from plagiarism_backend import main_plagiarism_pipeline

# Configure Streamlit page
st.set_page_config(
    page_title="Plagiarism Detection System",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem 0;
        margin-bottom: 2rem;
    }
    .upload-section {
        border: 2px dashed #cccccc;
        border-radius: 10px;
        padding: 2rem;
        text-align: center;
        margin: 1rem 0;
    }
    .status-box {
        border-radius: 10px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .warning-box {
        background-color: #fff3cd;
        border: 1px solid #ffeaa7;
        color: #856404;
    }
    .error-box {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
    }
    .info-box {
        background-color: #d1ecf1;
        border: 1px solid #bee5eb;
        color: #0c5460;
    }
</style>
""", unsafe_allow_html=True)

def create_risk_chart(plagiarism_results):
    """Create a risk distribution chart"""
    if not plagiarism_results:
        return None
    
    scores = [result['similarity_score'] for result in plagiarism_results.values()]
    
    # Categorize scores
    high_risk = sum(1 for score in scores if score >= 61)
    medium_risk = sum(1 for score in scores if 41 <= score < 61)
    low_risk = sum(1 for score in scores if score < 41)
    
    # Create pie chart
    fig = go.Figure(data=[go.Pie(
        labels=['Low Risk (0-40%)', 'Medium Risk (41-60%)', 'High Risk (61-100%)'],
        values=[low_risk, medium_risk, high_risk],
        marker_colors=['#28a745', '#ffc107', '#dc3545'],
        hole=0.4
    )])
    
    fig.update_layout(
        title="Risk Distribution",
        font=dict(size=12),
        height=400,
        showlegend=True
    )
    
    return fig

def create_scores_chart(plagiarism_results):
    """Create a bar chart of similarity scores"""
    if not plagiarism_results:
        return None
    
    ac_nums = list(plagiarism_results.keys())
    scores = [plagiarism_results[ac]['similarity_score'] for ac in ac_nums]
    
    # Sort by A.C. number
    sorted_data = sorted(zip(ac_nums, scores), key=lambda x: [int(i) for i in x[0].split('.')])
    ac_nums_sorted, scores_sorted = zip(*sorted_data)
    
    # Color code based on risk level
    colors = []
    for score in scores_sorted:
        if score >= 61:
            colors.append('#dc3545')  # Red for high risk
        elif score >= 41:
            colors.append('#ffc107')  # Yellow for medium risk
        else:
            colors.append('#28a745')  # Green for low risk
    
    fig = go.Figure(data=[go.Bar(
        x=[f"A.C. {ac}" for ac in ac_nums_sorted],
        y=scores_sorted,
        marker_color=colors,
        text=[f"{score}%" for score in scores_sorted],
        textposition='outside'
    )])
    
    fig.update_layout(
        title="Similarity Scores by A.C. Section",
        xaxis_title="A.C. Sections",
        yaxis_title="Similarity Score (%)",
        font=dict(size=12),
        height=400,
        yaxis=dict(range=[0, 100])
    )
    
    return fig

def main():
    # Header
    st.markdown('<div class="main-header">', unsafe_allow_html=True)
    st.title("🔍 Plagiarism Detection System")
    st.markdown("Upload your DOCX or PDF document for AI-powered plagiarism analysis")
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Initialize session state
    if 'analysis_results' not in st.session_state:
        st.session_state.analysis_results = None
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    
    # File upload section
    st.markdown('<div class="upload-section">', unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "Choose a document file",
        type=['docx', 'pdf'],
        help="Upload a DOCX or PDF file containing A.C. sections for plagiarism analysis"
    )
    st.markdown('</div>', unsafe_allow_html=True)
    
    if uploaded_file is not None:
        # Display file information
        st.markdown('<div class="status-box info-box">', unsafe_allow_html=True)
        st.write(f"**File:** {uploaded_file.name}")
        st.write(f"**Size:** {uploaded_file.size:,} bytes")
        st.write(f"**Type:** {uploaded_file.type}")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Analyze button
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            analyze_button = st.button(
                "🚀 Start Analysis",
                type="primary",
                disabled=st.session_state.processing,
                use_container_width=True
            )
        
        if analyze_button and not st.session_state.processing:
            st.session_state.processing = True
            st.session_state.analysis_results = None
            
            # Progress tracking
            progress_container = st.container()
            with progress_container:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                def update_progress(message, progress):
                    progress_bar.progress(progress / 100)
                    status_text.text(f"🔄 {message}")
                
                # Run analysis
                try:
                    results = main_plagiarism_pipeline(uploaded_file, update_progress)
                    st.session_state.analysis_results = results
                    
                except Exception as e:
                    st.error(f"Analysis failed: {str(e)}")
                    results = {'success': False, 'error': str(e)}
                
                finally:
                    st.session_state.processing = False
                    # Clear progress indicators
                    progress_bar.empty()
                    status_text.empty()
    
    # Display results if available
    if st.session_state.analysis_results:
        results = st.session_state.analysis_results
        
        if results['success']:
            # Success message
            st.markdown('<div class="status-box success-box">', unsafe_allow_html=True)
            st.write("✅ **Analysis completed successfully!**")
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Results summary
            st.header("📊 Analysis Summary")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("A.C. Sections Found", len(results['ac_sections']))
            with col2:
                st.metric("Sections Analyzed", len(results['plagiarism_results']))
            with col3:
                processing_time = results['processing_stats']['total_time']
                st.metric("Processing Time", f"{processing_time:.1f}s")
            with col4:
                cache_hits = results['processing_stats']['cache_hits']
                st.metric("Cache Hits", cache_hits)
            
            # Domain classification
            if 'domain' in results:
                st.markdown('<div class="status-box info-box">', unsafe_allow_html=True)
                st.write(f"**Document Domain:** {results['domain']}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            # Charts
            if results['plagiarism_results']:
                st.header("📈 Visual Analysis")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    risk_chart = create_risk_chart(results['plagiarism_results'])
                    if risk_chart:
                        st.plotly_chart(risk_chart, use_container_width=True)
                
                with col2:
                    scores_chart = create_scores_chart(results['plagiarism_results'])
                    if scores_chart:
                        st.plotly_chart(scores_chart, use_container_width=True)
                
                # Detailed results table
                st.header("📋 Detailed Results")
                
                # Create dataframe for results
                table_data = []
                for ac_num, result in results['plagiarism_results'].items():
                    risk_level = "🔴 High" if result['similarity_score'] >= 61 else "🟡 Medium" if result['similarity_score'] >= 41 else "🟢 Low"
                    table_data.append({
                        'A.C. Section': ac_num,
                        'Similarity Score': f"{result['similarity_score']}%",
                        'Risk Level': risk_level,
                        'Confidence': result['confidence_level'],
                        'Primary Concerns': len(result.get('primary_concerns', []))
                    })
                
                df = pd.DataFrame(table_data)
                st.dataframe(df, use_container_width=True)
                
                # Expandable detailed analysis for each section
                st.header("🔍 Detailed Analysis")
                
                for ac_num, result in results['plagiarism_results'].items():
                    with st.expander(f"A.C. {ac_num} - {result['similarity_score']}% similarity"):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.write(f"**Confidence Level:** {result['confidence_level']}")
                            st.write(f"**Risk Assessment:** {result.get('risk_assessment', 'Not specified')}")
                        
                        with col2:
                            st.write(f"**Analysis Date:** {result.get('analysis_timestamp', 'Not specified')}")
                            st.write(f"**Content Hash:** {result.get('content_hash', 'Not available')[:12]}...")
                        
                        if result.get('primary_concerns'):
                            st.write("**Primary Concerns:**")
                            for concern in result['primary_concerns']:
                                st.write(f"• {concern}")
                        
                        if result.get('detailed_analysis'):
                            st.write("**Detailed Analysis:**")
                            st.write(result['detailed_analysis'])
                        
                        if result.get('recommendations'):
                            st.write("**Recommendations:**")
                            st.write(result['recommendations'])
            
            # Download report
            st.header("📄 Download Report")
            
            if 'pdf_report' in results:
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    if uploaded_file:
                        st.download_button(
                            label="📥 Download PDF Report",
                            data=results['pdf_report'],
                            file_name=f"plagiarism_report_{uploaded_file.name.split('.')[0]}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
        
        else:
            # Error message
            st.markdown('<div class="status-box error-box">', unsafe_allow_html=True)
            st.write(f"❌ **Analysis failed:** {results.get('error', 'Unknown error')}")
            st.markdown('</div>', unsafe_allow_html=True)
    
    # Help section
    with st.expander("ℹ️ Help & Information"):
        st.write("""
        **How to use this tool:**
        1. Upload a DOCX or PDF file containing A.C. (Assessment Criteria) sections
        2. Click "Start Analysis" to begin the plagiarism detection process
        3. Review the results and download the detailed PDF report
        
        **Supported file formats:**
        - Microsoft Word documents (.docx)
        - PDF documents (.pdf)
        
        **Similarity Score Interpretation:**
        - 0-40%: Low risk (minimal plagiarism indicators)
        - 41-60%: Medium risk (requires review)
        - 61-100%: High risk (significant plagiarism indicators)
        
        **Features:**
        - AI-powered analysis using Google Gemini
        - Automatic domain classification
        - Intelligent caching for faster processing
        - Comprehensive PDF reporting
        - Real-time progress tracking
        """)

if __name__ == "__main__":
    main()
