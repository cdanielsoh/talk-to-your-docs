import React, { useState, useEffect, useRef } from 'react';
import {
  List,
  ListItem,
  ListItemText,
  ListItemAvatar,
  ListItemSecondaryAction,
  Avatar,
  IconButton,
  Typography,
  Paper,
  Chip,
  Box,
  CircularProgress,
  Divider,
  Button,
  Collapse,
  Tooltip,
  Grid
} from '@mui/material';
import DescriptionIcon from '@mui/icons-material/Description';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';

const TERMINAL_STATES = ['COMPLETED', 'ERROR'];
const POLLING_INTERVAL = 10000; // 10 seconds

const DocumentList = ({ apiUrl, cloudFrontDomain, onSelectDocument }) => {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [isPolling, setIsPolling] = useState(true);
  const pollingIntervalRef = useRef(null);

  // Function to fetch document list
  const fetchDocuments = async () => {
    if (!apiUrl) return;

    setLoading(documents.length === 0); // Only show loading on initial fetch
    setError(null);

    try {
      console.log(`Fetching documents from ${apiUrl}/documents`);
      const response = await fetch(`${apiUrl}/documents`);
      if (!response.ok) {
        throw new Error(`Failed to fetch documents. Status: ${response.status}`);
      }

      const data = await response.json();
      console.log('Received document data:', data);
      setDocuments(data.documents || []);

      // Check if all documents are in terminal states (COMPLETED or ERROR)
      const allDocumentsProcessed = (data.documents || []).every(
        doc => TERMINAL_STATES.includes(doc.status)
      );

      // If all documents are processed, we can stop polling
      if (allDocumentsProcessed && data.documents.length > 0) {
        console.log('All documents processed, stopping polling');
        setIsPolling(false);
      }
    } catch (error) {
      console.error('Error fetching documents:', error);
      setError(`Failed to load documents: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Set up polling effect
  useEffect(() => {
    // Initial fetch
    fetchDocuments();

    // Set up polling if needed
    if (isPolling) {
      pollingIntervalRef.current = setInterval(fetchDocuments, POLLING_INTERVAL);
    }

    // Cleanup function
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }, [apiUrl, isPolling]);

  // Effect to update polling state based on document statuses
  useEffect(() => {
    const allDocumentsProcessed = documents.length > 0 &&
      documents.every(doc => TERMINAL_STATES.includes(doc.status));

    if (allDocumentsProcessed && isPolling) {
      setIsPolling(false);
      console.log('All documents processed, polling stopped');
    }
  }, [documents, isPolling]);

  // Toggle expand/collapse for a document
  const toggleExpand = (id) => {
    setExpandedId(expandedId === id ? null : id);
  };

  // Convert S3 URL to CloudFront URL
  const getDocumentUrl = (s3Url) => {
    if (!s3Url || !cloudFrontDomain) return '#';

    if (s3Url.startsWith('s3://')) {
      const parts = s3Url.replace('s3://', '').split('/');
      const bucketName = parts[0];
      const key = parts.slice(1).join('/');
      return `https://${cloudFrontDomain}/${key}`;
    }

    return s3Url;
  };

  // Render document status chip
  const renderStatusChip = (status) => {
    let color = 'default';
    let tooltip = '';

    switch (status) {
      case 'UPLOADED':
        color = 'info';
        tooltip = 'Document has been uploaded and is waiting to be processed';
        break;
      case 'PROCESSING':
        color = 'warning';
        tooltip = 'Document is being prepared for the knowledge base';
        break;
      case 'INGESTING':
        color = 'warning';
        tooltip = 'Document is being ingested by the Bedrock Knowledge Base';
        break;
      case 'COMPLETED':
        color = 'success';
        tooltip = 'Document has been successfully processed and is ready for use';
        break;
      case 'ERROR':
        color = 'error';
        tooltip = 'An error occurred during document processing';
        break;
      default:
        color = 'default';
        tooltip = 'Unknown status';
    }

    return (
      <Tooltip title={tooltip}>
        <Chip
          label={status}
          color={color}
          size="small"
          variant="outlined"
        />
      </Tooltip>
    );
  };

  // Render index status icon with tooltip
  const renderIndexStatus = (status, label) => {
    let icon = <HourglassEmptyIcon fontSize="small" color="action" />;
    let tooltipText = `${label} index is pending`;
    let color = "text.secondary";

    switch (status) {
      case 'COMPLETED':
        icon = <CheckCircleOutlineIcon fontSize="small" color="success" />;
        tooltipText = `${label} index is complete`;
        color = "success.main";
        break;
      case 'PENDING':
        icon = <HourglassEmptyIcon fontSize="small" color="action" />;
        tooltipText = `${label} index is pending`;
        break;
      case 'PROCESSING':
        icon = <CircularProgress size={16} />;
        tooltipText = `${label} index is processing`;
        break;
      case 'INGESTING':
        icon = <CircularProgress size={16} />;
        tooltipText = `${label} index is being ingested`;
        break;
      case 'ERROR':
        icon = <ErrorOutlineIcon fontSize="small" color="error" />;
        tooltipText = `${label} index encountered an error`;
        color = "error.main";
        break;
      default:
        icon = <HourglassEmptyIcon fontSize="small" color="action" />;
        tooltipText = `${label} index status: ${status}`;
    }

    return (
      <Tooltip title={tooltipText}>
        <Box sx={{ display: 'flex', alignItems: 'center', mr: 2 }}>
          {icon}
          <Typography variant="caption" color={color} sx={{ ml: 0.5 }}>
            {label}
          </Typography>
        </Box>
      </Tooltip>
    );
  };

  // Format timestamp
  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'Unknown';

    try {
      const date = new Date(timestamp);
      return date.toLocaleString();
    } catch (e) {
      return timestamp;
    }
  };

  // Format token usage data safely
  const formatTokenUsage = (tokenUsage) => {
    if (!tokenUsage) return 'No token usage data';

    try {
      // If token usage is already a string, just return it
      if (typeof tokenUsage === 'string') return tokenUsage;

      // If it's an object, format it nicely
      if (typeof tokenUsage === 'object') {
        // Create a more human-readable version of the keys
        const readableLabels = {
          'input_tokens': 'Input Tokens',
          'output_tokens': 'Output Tokens',
          'cache_read_input_tokens': 'Cache Read Tokens',
          'cache_write_input_tokens': 'Cache Write Tokens',
          'inputTokens': 'Input Tokens',
          'outputTokens': 'Output Tokens',
          'cacheReadInputTokens': 'Cache Read Tokens',
          'cacheWriteInputTokens': 'Cache Write Tokens',
        };

        // Check if all token values are zero
        const allZero = Object.values(tokenUsage).every(value => {
          const numValue = typeof value === 'number' ? value :
                        (typeof value === 'string' ? parseFloat(value) : 0);
          return numValue === 0;
        });

        if (allZero) {
          return (
            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
              Token usage not yet available or processing
            </Typography>
          );
        }

        // Format and display token usage values
        return (
          <Grid container spacing={1}>
            {Object.entries(tokenUsage).map(([key, value]) => {
              // Skip any entries with null, undefined, or N/A values
              if (value === null || value === undefined || value === 'N/A') {
                return null;
              }

              const label = readableLabels[key] || key.replace(/_/g, ' ');

              // Convert value to number if possible for formatting
              let displayValue;
              try {
                // Handle DynamoDB-style values: {"N": "34930"}
                if (typeof value === 'object' && value !== null && 'N' in value) {
                  displayValue = parseInt(value.N, 10).toLocaleString();
                } else {
                  // Normal numbers or strings
                  const numValue = typeof value === 'number' ? value :
                                (typeof value === 'string' ? parseFloat(value) : value);
                  displayValue = !isNaN(numValue) ? numValue.toLocaleString() : value.toString();
                }
              } catch (e) {
                displayValue = String(value);
              }

              return (
                <Grid item xs={6} key={key}>
                  <Typography variant="body2">
                    <strong>{label}:</strong> {displayValue}
                  </Typography>
                </Grid>
              );
            })}
          </Grid>
        );
      }

      // Handle DynamoDB-style values at top level: {"N": "34930"}
      if (typeof tokenUsage === 'object' && tokenUsage !== null) {
        // Check for special N format
        const entries = Object.entries(tokenUsage);
        if (entries.length === 1 && entries[0][0] === 'N') {
          return `${parseInt(entries[0][1], 10).toLocaleString()} tokens`;
        }
      }

      // Fallback for any other type
      return JSON.stringify(tokenUsage);
    } catch (e) {
      console.error('Error formatting token usage:', e);
      return 'Error displaying token usage data';
    }
  };

  // Handle refresh button click
  const handleRefresh = () => {
    fetchDocuments();
  };

  // Handle resume polling button click
  const handleResumePolling = () => {
    setIsPolling(true);
  };

  // Handle document selection
  const handleSelectDocument = (document) => {
    if (onSelectDocument) {
      const documentWithUrl = {
        ...document,
        url: getDocumentUrl(document.s3Url),
        title: document.fileName
      };
      onSelectDocument(documentWithUrl);
    }
  };

  return (
    <Paper elevation={0} sx={{ backgroundColor: 'background.default' }}>
      <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="h6">Documents</Typography>
        <Box sx={{ display: 'flex', alignItems: 'center' }}>
          {!isPolling && documents.length > 0 && (
            <Tooltip title="Resume automatic updates">
              <Button
                size="small"
                onClick={handleResumePolling}
                sx={{ mr: 1 }}
              >
                Auto-update
              </Button>
            </Tooltip>
          )}
          <Tooltip title="Refresh document list">
            <IconButton onClick={handleRefresh} disabled={loading}>
              <RefreshIcon />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      {loading && documents.length === 0 ? (
        <Box sx={{ p: 4, textAlign: 'center' }}>
          <CircularProgress size={30} />
          <Typography variant="body2" sx={{ mt: 2 }}>
            Loading documents...
          </Typography>
        </Box>
      ) : error ? (
        <Box sx={{ p: 2 }}>
          <Typography color="error">{error}</Typography>
        </Box>
      ) : documents.length === 0 ? (
        <Box sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body1">
            No documents uploaded yet
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Upload a PDF to get started
          </Typography>
        </Box>
      ) : (
        <List sx={{ maxHeight: '500px', overflowY: 'auto' }}>
          {documents.map((doc, index) => (
            <React.Fragment key={doc.id}>
              {index > 0 && <Divider component="li" />}
              <ListItem
                button
                onClick={() => handleSelectDocument(doc)}
                sx={{
                  bgcolor: 'white',
                  ':hover': {
                    bgcolor: 'rgba(0, 0, 0, 0.04)'
                  },
                  // Highlight processing documents
                  ...(doc.status === 'PROCESSING' || doc.status === 'INGESTING' ? {
                    bgcolor: 'rgba(255, 152, 0, 0.05)',
                  } : {})
                }}
              >
                <ListItemAvatar>
                  <Avatar>
                    <DescriptionIcon />
                  </Avatar>
                </ListItemAvatar>
                <ListItemText
                  primary={doc.fileName}
                  secondary={
                    <React.Fragment>
                      <Typography component="span" variant="body2" color="text.secondary">
                        {formatTimestamp(doc.uploadTime)}
                      </Typography>
                      <Box sx={{ mt: 0.5, display: 'flex', alignItems: 'center' }}>
                        {renderStatusChip(doc.status)}
                        {doc.statusMessage && (
                          <Tooltip title={doc.statusMessage}>
                            <IconButton size="small" sx={{ ml: 0.5 }}>
                              <HelpOutlineIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                      </Box>

                      {/* Index statuses */}
                      {doc.indexStatus && (
                        <Box sx={{ mt: 0.5, display: 'flex', alignItems: 'center' }}>
                          {renderIndexStatus(doc.indexStatus.contextual_retrieval, 'CR')}
                          {renderIndexStatus(doc.indexStatus.knowledge_base, 'KB')}
                        </Box>
                      )}
                    </React.Fragment>
                  }
                />
                <ListItemSecondaryAction>
                  <IconButton edge="end" onClick={(e) => {
                    e.stopPropagation();
                    toggleExpand(doc.id);
                  }}>
                    {expandedId === doc.id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                  </IconButton>
                </ListItemSecondaryAction>
              </ListItem>
              <Collapse in={expandedId === doc.id} timeout="auto" unmountOnExit>
                <Box sx={{ p: 2, pl: 9, bgcolor: 'rgba(0, 0, 0, 0.02)' }}>
                  <Typography variant="subtitle2" gutterBottom>
                    Status: <strong>{doc.status}</strong>
                  </Typography>

                  {doc.statusMessage && (
                    <Typography variant="body2" color="text.secondary" paragraph>
                      {doc.statusMessage}
                    </Typography>
                  )}

                  {/* Detailed index status information */}
                  {doc.indexStatus && (
                    <Box sx={{ mb: 1 }}>
                      <Typography variant="subtitle2" gutterBottom>
                        Index Statuses:
                      </Typography>
                      <Grid container spacing={1} sx={{ ml: 1 }}>
                        <Grid item xs={6}>
                          <Typography variant="body2">
                            <strong>Contextual Retrieval:</strong> {doc.indexStatus.contextual_retrieval}
                          </Typography>
                        </Grid>
                        <Grid item xs={6}>
                          <Typography variant="body2">
                            <strong>Knowledge Base:</strong> {doc.indexStatus.knowledge_base}
                          </Typography>
                        </Grid>
                      </Grid>
                    </Box>
                  )}

                  {doc.ingestionJobId && (
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      <strong>Ingestion Job ID:</strong> <code>{doc.ingestionJobId}</code><br />
                      <strong>Ingestion Status:</strong> {doc.ingestionStatus || 'Unknown'}
                    </Typography>
                  )}

                  {doc.tokenUsage && (
                    <Box sx={{ mt: 1, mb: 1 }}>
                      <Typography variant="subtitle2" gutterBottom>
                        Token Usage:
                      </Typography>
                      <Box sx={{ ml: 1, mt: 0.5, fontSize: '0.85rem' }}>
                        {formatTokenUsage(doc.tokenUsage)}
                      </Box>
                    </Box>
                  )}

                  <Button
                    variant="outlined"
                    size="small"
                    endIcon={<OpenInNewIcon />}
                    href={getDocumentUrl(doc.s3Url)}
                    target="_blank"
                    onClick={(e) => e.stopPropagation()}
                    sx={{ mt: 1 }}
                  >
                    View Document
                  </Button>
                </Box>
              </Collapse>
            </React.Fragment>
          ))}
        </List>
      )}
    </Paper>
  );
};

export default DocumentList;