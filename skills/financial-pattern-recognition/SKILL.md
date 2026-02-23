---
name: financial-pattern-recognition
description: "Advanced corruption detection through financial flow analysis, campaign contribution patterns, contract award correlations, and pay-to-play scheme identification. Use this skill when analyzing government financial data, detecting bid rigging, identifying conflicts of interest, or mapping money influence pathways."
---

# Financial Pattern Recognition Skill

## Overview
Advanced capability for detecting corruption patterns through comprehensive analysis of financial flows, campaign contributions, contract awards, and economic relationships in government transparency data.

## Core Capabilities

### Money Flow Analysis
- Campaign contribution pattern detection
- Contract award timing correlation
- Unusual payment flow identification
- Shell company and intermediary tracking
- Cross-jurisdictional financial relationship mapping

### Corruption Pattern Detection
- Pay-to-play scheme identification
- Bid rigging pattern recognition
- Conflict of interest financial indicators
- Quid pro quo timing analysis
- Influence peddling financial signatures

### Financial Network Mapping
- Donor influence pathway analysis
- Vendor relationship tracking
- Financial intermediary identification
- Beneficial ownership chain analysis
- Economic pressure point detection

## Technical Implementation

### Required Libraries
```python
import pandas as pd
import numpy as np
import networkx as nx
import sklearn.cluster
import scipy.stats
import plotly.graph_objects as go
import datetime
import re
```

### Core Analysis Functions
```python
def analyze_contribution_timing(contributions, votes, window_days=30):
    """Detect contributions timed around key votes"""
    
def identify_unusual_amounts(financial_data, threshold_std=2.5):
    """Flag statistically unusual payment amounts"""
    
def map_shell_company_networks(business_filings, ownership_data):
    """Identify potential shell company structures"""
    
def correlate_contracts_contributions(contracts, contributions):
    """Find correlation between donations and contract awards"""
    
def detect_circular_payments(payment_flows):
    """Identify money laundering patterns"""
```

### Advanced Pattern Recognition
```python
def analyze_bundling_patterns(contributions):
    """Detect coordinated contribution schemes"""
    
def identify_straw_donors(contributor_data):
    """Flag potential fake or proxy contributors"""
    
def track_vendor_favoritism(contract_awards, vendor_relationships):
    """Identify patterns of preferential treatment"""
    
def analyze_family_financial_networks(personal_relationships, transactions):
    """Map family/personal financial connections"""
```

## Financial Data Sources Integration

### Campaign Finance Data
```python
# FEC API Integration
def fetch_fec_contributions(candidate_id, cycle):
    """Retrieve federal campaign finance data"""
    
# Cal-Access Integration  
def fetch_california_contributions(committee_id, year):
    """Retrieve California state campaign data"""
    
# Local Campaign Finance
def parse_local_finance_reports(pdf_files):
    """Extract data from local campaign finance PDFs"""
```

### Contract and Procurement Data
```python
# Federal Contracts (USASpending.gov)
def fetch_federal_contracts(agency, timeframe):
    """Retrieve federal contract award data"""
    
# State/Local Procurement
def scrape_procurement_portals(jurisdiction_urls):
    """Extract contract awards from local portals"""
    
# Vendor Registration Systems
def analyze_vendor_databases(registration_data):
    """Process vendor qualification and registration info"""
```

### Property and Asset Data
```python
# Real Estate Transactions
def analyze_property_records(county_assessor_data):
    """Process real estate ownership and transfer data"""
    
# Business Asset Tracking
def track_business_assets(secretary_of_state_filings):
    """Monitor business ownership and asset transfers"""
    
# Trust and LLC Analysis
def map_entity_ownership(business_entity_data):
    """Trace beneficial ownership through legal entities"""
```

## Corruption Detection Algorithms

### Pay-to-Play Detection
```python
def detect_pay_to_play(contributions, decisions, proximity_window=60):
    """
    Identify potential pay-to-play schemes
    
    Parameters:
    - contributions: DataFrame of campaign contributions
    - decisions: DataFrame of government decisions/votes
    - proximity_window: Days before/after decision to check
    
    Returns:
    - Suspicious patterns with correlation scores
    """
    
    patterns = []
    
    for decision in decisions.itertuples():
        # Find contributions within window
        decision_date = decision.date
        window_start = decision_date - timedelta(days=proximity_window)
        window_end = decision_date + timedelta(days=proximity_window)
        
        related_contributions = contributions[
            (contributions.date >= window_start) & 
            (contributions.date <= window_end)
        ]
        
        # Check for unusual amounts or new donors
        for contrib in related_contributions.itertuples():
            # Correlation analysis
            pattern_score = calculate_correlation_score(contrib, decision)
            if pattern_score > threshold:
                patterns.append({
                    'decision_id': decision.id,
                    'contribution_id': contrib.id,
                    'correlation_score': pattern_score,
                    'time_delta': abs((decision_date - contrib.date).days),
                    'pattern_type': 'pay_to_play'
                })
    
    return patterns
```

### Bid Rigging Detection
```python
def detect_bid_rigging(contract_awards, bid_data):
    """
    Identify potential bid rigging patterns
    
    Indicators:
    - Rotating winning patterns among small set of vendors
    - Unusually high winning bid margins
    - Geographic patterns in vendor selection
    - Timing patterns in bid submissions
    """
    
    # Analyze winning patterns
    vendor_wins = contract_awards.groupby('vendor').agg({
        'award_amount': ['count', 'sum', 'mean'],
        'bid_margin': 'mean'
    })
    
    # Check for rotation patterns
    rotation_score = analyze_vendor_rotation(contract_awards)
    
    # Identify suspicious margins
    margin_outliers = identify_margin_outliers(bid_data)
    
    return {
        'rotation_patterns': rotation_score,
        'margin_anomalies': margin_outliers,
        'vendor_concentration': vendor_wins
    }
```

### Conflict of Interest Detection
```python
def detect_conflicts_of_interest(officials, business_interests, decisions):
    """
    Identify financial conflicts of interest
    
    Cross-references:
    - Official's business interests
    - Family financial relationships  
    - Investment portfolios
    - Decision-making involvement
    """
    
    conflicts = []
    
    for official in officials.itertuples():
        # Get official's financial interests
        interests = business_interests[
            business_interests.official_id == official.id
        ]
        
        # Find decisions this official participated in
        official_decisions = decisions[
            decisions.participants.str.contains(official.name)
        ]
        
        # Check for conflicts
        for decision in official_decisions.itertuples():
            for interest in interests.itertuples():
                conflict_score = calculate_conflict_score(decision, interest)
                if conflict_score > threshold:
                    conflicts.append({
                        'official': official.name,
                        'decision': decision.description,
                        'conflict_type': interest.interest_type,
                        'conflict_score': conflict_score
                    })
    
    return conflicts
```

## Advanced Analytics

### Statistical Analysis
```python
def perform_statistical_tests(financial_patterns):
    """Statistical significance testing for identified patterns"""
    
    # Chi-square test for independence
    chi2_results = scipy.stats.chi2_contingency(contribution_timing_table)
    
    # Correlation analysis
    correlation_matrix = financial_data.corr()
    
    # Outlier detection using z-scores
    z_scores = np.abs(scipy.stats.zscore(amounts))
    outliers = amounts[z_scores > 3]
    
    return {
        'chi2_test': chi2_results,
        'correlations': correlation_matrix,
        'outliers': outliers
    }
```

### Machine Learning Detection
```python
def train_corruption_detector(training_data):
    """Train ML model to detect corruption patterns"""
    
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    
    # Feature engineering
    features = engineer_corruption_features(training_data)
    
    # Train model
    X_train, X_test, y_train, y_test = train_test_split(
        features, labels, test_size=0.2
    )
    
    model = RandomForestClassifier(n_estimators=100)
    model.fit(X_train, y_train)
    
    return model

def engineer_corruption_features(data):
    """Create features for corruption detection"""
    
    features = pd.DataFrame()
    
    # Timing features
    features['contribution_vote_proximity'] = calculate_proximity_scores(data)
    features['unusual_timing_flag'] = detect_unusual_timing(data)
    
    # Amount features  
    features['amount_zscore'] = calculate_amount_zscores(data)
    features['round_number_flag'] = detect_round_numbers(data)
    
    # Network features
    features['network_centrality'] = calculate_network_centrality(data)
    features['intermediary_count'] = count_intermediaries(data)
    
    return features
```

### Predictive Analytics
```python
def predict_corruption_risk(current_patterns, historical_model):
    """Predict likelihood of corruption based on current patterns"""
    
    # Calculate risk indicators
    risk_features = calculate_risk_features(current_patterns)
    
    # Apply trained model
    corruption_probability = historical_model.predict_proba(risk_features)
    
    # Generate risk assessment
    risk_assessment = {
        'overall_risk_score': corruption_probability[0][1],
        'key_risk_factors': identify_top_risk_factors(risk_features),
        'recommended_investigations': suggest_investigations(risk_features)
    }
    
    return risk_assessment
```

## Visualization and Reporting

### Financial Flow Diagrams
```python
def create_money_flow_visualization(financial_data):
    """Create interactive Sankey diagram of money flows"""
    
    fig = go.Figure(data=[go.Sankey(
        node = dict(
            pad = 15,
            thickness = 20,
            line = dict(color = "black", width = 0.5),
            label = entity_labels,
            color = "blue"
        ),
        link = dict(
            source = source_indices,
            target = target_indices, 
            value = flow_amounts
        )
    )])
    
    return fig

def create_timeline_correlation(contributions, decisions):
    """Create timeline showing contribution/decision correlations"""
    
    fig = go.Figure()
    
    # Add contribution events
    fig.add_trace(go.Scatter(
        x=contributions.date,
        y=contributions.amount,
        mode='markers',
        name='Contributions',
        marker=dict(color='red', size=8)
    ))
    
    # Add decision events
    for decision in decisions.itertuples():
        fig.add_vline(
            x=decision.date,
            line_dash="dash",
            line_color="blue",
            annotation_text=decision.description
        )
    
    return fig
```

### Automated Report Generation
```python
def generate_corruption_report(analysis_results):
    """Generate comprehensive corruption analysis report"""
    
    report = {
        'executive_summary': generate_executive_summary(analysis_results),
        'key_findings': summarize_key_findings(analysis_results),
        'statistical_analysis': format_statistical_results(analysis_results),
        'visualizations': create_report_visualizations(analysis_results),
        'recommendations': generate_recommendations(analysis_results)
    }
    
    return report

def generate_executive_summary(results):
    """Create executive summary of findings"""
    
    summary = f"""
    CORRUPTION PATTERN ANALYSIS SUMMARY
    
    Analysis Period: {results['analysis_period']}
    Total Transactions Analyzed: {results['transaction_count']:,}
    
    KEY FINDINGS:
    - {len(results['pay_to_play_patterns'])} potential pay-to-play schemes identified
    - {len(results['bid_rigging_patterns'])} possible bid rigging patterns detected
    - {len(results['conflict_patterns'])} conflicts of interest flagged
    
    RISK ASSESSMENT: {results['overall_risk_level']}
    
    IMMEDIATE ACTIONS RECOMMENDED:
    {format_recommendations(results['high_priority_actions'])}
    """
    
    return summary
```

## Data Export and Integration

### Database Integration
```python
def export_to_database(analysis_results, database_connection):
    """Export analysis results to Anti-Palantir database"""
    
    # Export to PostgreSQL structured tables
    export_to_postgresql(analysis_results['structured_data'])
    
    # Export to Neo4j for network analysis
    export_to_neo4j(analysis_results['network_data'])
    
    # Store documents in document store
    export_documents(analysis_results['supporting_documents'])
```

### API Integration
```python
def create_financial_api_endpoints():
    """Create API endpoints for financial pattern access"""
    
    @app.route('/api/corruption-patterns')
    def get_corruption_patterns():
        """Return current corruption pattern analysis"""
        
    @app.route('/api/risk-assessment/<entity>')
    def get_risk_assessment(entity):
        """Return risk assessment for specific entity"""
        
    @app.route('/api/financial-networks')
    def get_financial_networks():
        """Return financial relationship networks"""
```

## Performance Optimization

### Large Dataset Handling
```python
def optimize_for_large_datasets(financial_data):
    """Optimize analysis for large financial datasets"""
    
    # Chunk processing for memory efficiency
    chunk_size = 10000
    results = []
    
    for chunk in pd.read_csv(data_file, chunksize=chunk_size):
        chunk_results = analyze_chunk(chunk)
        results.append(chunk_results)
    
    # Combine results
    final_results = combine_chunk_results(results)
    
    return final_results

def implement_caching():
    """Implement intelligent caching for expensive operations"""
    
    from functools import lru_cache
    
    @lru_cache(maxsize=1000)
    def cached_network_analysis(entity_id):
        """Cache network analysis results"""
        return perform_network_analysis(entity_id)
```

## Security and Compliance

### Data Protection
```python
def anonymize_sensitive_data(financial_data):
    """Anonymize personally identifiable information"""
    
    # Hash personal identifiers
    financial_data['donor_id'] = financial_data['donor_name'].apply(
        lambda x: hashlib.sha256(x.encode()).hexdigest()[:16]
    )
    
    # Remove direct personal identifiers
    financial_data.drop(['ssn', 'full_address'], axis=1, inplace=True)
    
    return financial_data

def audit_analysis_access(user_id, analysis_type):
    """Log all access to financial analysis functions"""
    
    audit_log = {
        'timestamp': datetime.now(),
        'user_id': user_id,
        'analysis_type': analysis_type,
        'ip_address': get_client_ip(),
        'action': 'financial_analysis_access'
    }
    
    log_audit_event(audit_log)
```

## Success Metrics

### Detection Accuracy
- False positive rate for corruption pattern detection
- True positive rate for known corruption cases
- Time from pattern emergence to detection
- Correlation accuracy between financial flows and decisions

### Analysis Performance
- Processing speed for large financial datasets
- Memory efficiency for complex network analysis
- Real-time detection capability for new transactions
- System scalability for multiple jurisdictions

### Actionable Intelligence
- Number of investigations initiated from financial analysis
- Conviction rate for cases with financial pattern evidence
- Policy changes implemented based on corruption detection
- Transparency improvements in financial reporting

---

*"Follow the money, because money never lies about where power really flows"*

## Integration with Anti-Palantir System

This Financial Pattern Recognition skill integrates seamlessly with:
- **Government Portal Navigation**: Automated collection of financial disclosure data
- **Network Analysis**: Enhanced relationship mapping with financial connections
- **Document OCR**: Extraction of financial data from PDF reports and filings

Combined, these skills create a comprehensive corruption detection system that can automatically identify suspicious financial patterns in government operations and provide evidence-ready analysis for transparency investigations.
