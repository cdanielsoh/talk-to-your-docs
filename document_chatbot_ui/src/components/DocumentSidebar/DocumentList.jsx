import React, { useState, useEffect } from 'react';
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
  Tooltip
} from '@mui/material';
import DescriptionIcon from '@mui/icons-material/Description';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';

const DocumentList = ({ apiUrl, cloudFrontDomain, onSelectDocument }) => {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedId, setExpandedId] = useState(null);

  // Function to fetch document list
  const fetchDocuments = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${apiUrl}/documents`);
      if (!response.ok) {
        throw new Error('Failed to fetch documents');
      }

      const data = await response.json();
      setDocuments(data.documents || []);
    } catch (error) {
      console.error('Error fetching documents:', error);
      setError('Failed to load documents. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // Fetch documents on component mount
  useEffect(() => {
    if (apiUrl) {
      fetchDocuments();

      // Set up polling every 10 seconds to check for status updates
      const intervalId = setInterval(fetchDocuments, 10000);

      // Clean up interval on unmount
      return () => clearInterval(intervalId);
    }
  }, [apiUrl]);

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

  // Handle refresh button click
  const handleRefresh = () => {
    fetchDocuments();
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
        <IconButton onClick={handleRefresh} disabled={loading}>
          <RefreshIcon />
        </IconButton>
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

                  {doc.ingestionJobId && (
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      Ingestion Job ID: <code>{doc.ingestionJobId}</code>
                    </Typography>
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