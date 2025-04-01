import React, { useState, useEffect } from 'react';
import Chat from '../Chat/Chat';
import DocumentViewer from '../DocumentViewer/DocumentViewer';
import Selector from '../Selector/Selector'; // Updated import
import { ThemeProvider, createTheme } from '@mui/material/styles';
import { CircularProgress, Box, Typography, Button, ButtonGroup, Paper } from '@mui/material';
import ArrowBackIosNewIcon from '@mui/icons-material/ArrowBackIosNew';
import ArrowForwardIosIcon from '@mui/icons-material/ArrowForwardIos';
import './Layout.css';

const theme = createTheme({
  palette: {
    primary: {
      main: '#2563eb',
    },
    secondary: {
      main: '#3b82f6',
    },
    background: {
      default: '#f8fafc',
    },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
  },
});

function Layout() {
  const [messages, setMessages] = useState([]);
  const [availableSources, setAvailableSources] = useState([]);
  const [currentDocumentIndex, setCurrentDocumentIndex] = useState(0);
  const [wsConnection, setWsConnection] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(true);
  const [connectionError, setConnectionError] = useState(null);
  const [aiRespondingMessageId, setAiRespondingMessageId] = useState(null);
  // Add state for search method selection
  const [selectedModel, setSelectedModel] = useState('amazon.nova-pro-v1:0');
  const [selectedSearchMethod, setSelectedSearchMethod] = useState('opensearch');
  const [config, setConfig] = useState(null);
  const [configLoading, setConfigLoading] = useState(true);

  // Current document derived from available sources and current index
  const currentDocument = availableSources.length > 0 ? availableSources[currentDocumentIndex] : null;

  // Function to handle model changes
  const handleModelChange = (modelId) => {
    setSelectedModel(modelId);
  };

  // Function to handle search method changes
  const handleSearchMethodChange = (methodId) => {
    setSelectedSearchMethod(methodId);
  };

  // Function to navigate between documents
  const navigateDocument = (direction) => {
    if (availableSources.length === 0) return;

    setCurrentDocumentIndex(prevIndex => {
      if (direction === 'next') {
        return (prevIndex + 1) % availableSources.length;
      } else {
        return prevIndex === 0 ? availableSources.length - 1 : prevIndex - 1;
      }
    });
  };

  // Load config.json first
  useEffect(() => {
    const loadConfig = async () => {
      try {
        const response = await fetch('/config.json');
        if (!response.ok) {
          throw new Error(`Failed to load config: ${response.statusText}`);
        }
        const configData = await response.json();
        setConfig(configData);
        setConfigLoading(false);
      } catch (err) {
        console.error('Error loading configuration:', err);
        setConnectionError('Failed to load application configuration. Please refresh the page or contact support.');
        setConfigLoading(false);
        setIsConnecting(false);
      }
    };

    loadConfig();
  }, []);

  // Connect to WebSocket after config is loaded
  useEffect(() => {
    if (configLoading || !config) return;

    const wsUrl = config.websocketUrl;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('Connected to WebSocket');
      setIsConnected(true);
      setIsConnecting(false);
      setWsConnection(ws);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log("WebSocket message received:", data);

      // Extract the text content from wherever it might be in the response
      let textContent = null;
      if (data.type === 'text' && data.content) {
        textContent = data.content;
      } else if (data.text) {
        textContent = data.text;
      } else if (data.output && data.output.text) {
        textContent = data.output.text;
      }

      // If we have text content to display
      if (textContent !== null) {
        setMessages(prevMessages => {
          // If we already have an AI message we're building
          if (aiRespondingMessageId !== null) {
            // Return a new array with the AI message text updated
            return prevMessages.map(msg =>
              msg.id === aiRespondingMessageId
                ? {...msg, text: msg.text + textContent}
                : msg
            );
          } else {
            // Create a new AI message and store its ID
            const newMessageId = Date.now();
            setAiRespondingMessageId(newMessageId);

            return [...prevMessages, {
              id: newMessageId,
              text: textContent,
              sender: 'ai',
              timestamp: new Date().toISOString()
            }];
          }
        });
      }

      // Handle citation (newer format)
      if (data.type === 'citation' && data.sourceUrl) {
        // Check if this source is already in our list
        const existingIndex = availableSources.findIndex(source => source.id === data.sourceId);

        if (existingIndex >= 0) {
          // Source already exists, make it the current one
          setCurrentDocumentIndex(existingIndex);
        } else {
          // Add new source to the list
          const newSource = {
            id: data.sourceId,
            url: data.sourceUrl,
            title: `Source ${data.sourceId}`
          };

          // Use functional update to correctly set the index
          setAvailableSources(prev => {
            const newSources = [...prev, newSource];
            setCurrentDocumentIndex(newSources.length - 1);
            return newSources;
          });
        }
      }

      // Handle 'complete' message - signals end of AI response
      if (data.type === 'complete') {
        // Reset the AI responding message ID for the next interaction
        setAiRespondingMessageId(null);

        // Only update sources if we haven't received any yet
        if (data.sources && Object.keys(data.sources).length > 0 && availableSources.length === 0) {
          const completeSources = Object.entries(data.sources).map(([id, url]) => ({
            id,
            url,
            title: `Source ${id}`
          }));

          setAvailableSources(completeSources);
          setCurrentDocumentIndex(0);
        }
      }

      // Handle errors
      if (data.error || (data.type === 'error' && data.message)) {
        const errorMsg = data.error || data.message;
        setMessages(prev => [...prev, {
          id: Date.now(),
          text: `Error: ${errorMsg}`,
          sender: 'system',
          timestamp: new Date().toISOString()
        }]);
        setAiRespondingMessageId(null);
      }
    };

    ws.onclose = () => {
      console.log('Disconnected from WebSocket');
      setIsConnected(false);
      setIsConnecting(false);
      setAiRespondingMessageId(null);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setConnectionError('Failed to connect to the server. Please try again later.');
      setIsConnecting(false);
      setAiRespondingMessageId(null);
    };

    return () => {
      if (ws) ws.close();
    };
  }, [config, configLoading]);

  const handleSendMessage = (message) => {
    if (wsConnection && isConnected) {
      // Reset the AI responding message ID for a new conversation turn
      setAiRespondingMessageId(null);

      // Clear previous sources when starting a new conversation
      setAvailableSources([]);
      setCurrentDocumentIndex(0);

      // Add user message to chat
      setMessages(prev => [...prev, {
        id: Date.now(),
        text: message,
        sender: 'user',
        timestamp: new Date().toISOString()
      }]);

      // Send to WebSocket with model and search method information
      wsConnection.send(JSON.stringify({
        query: message,
        modelArn: selectedModel,
        searchMethod: selectedSearchMethod
      }));
    }
  };

  // If loading config or connecting, show a loading indicator
  if (configLoading || (isConnecting && !connectionError)) {
    return (
      <ThemeProvider theme={theme}>
        <Box className="connecting-container">
          <CircularProgress />
          <Typography variant="h6" sx={{ mt: 2 }}>
            {configLoading ? "Loading application..." : "Connecting to server..."}
          </Typography>
        </Box>
      </ThemeProvider>
    );
  }

  // If connection error, show error message
  if (connectionError) {
    return (
      <ThemeProvider theme={theme}>
        <Box className="error-container">
          <Typography variant="h6" color="error">
            {connectionError}
          </Typography>
        </Box>
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider theme={theme}>
      <div className="app-layout">
        {/* Selector container */}
        <Paper className="selector-container" elevation={1}>
          <Box sx={{ p: 2 }}>
            <Selector
              selectedModel={selectedModel}
              onModelChange={handleModelChange}
              selectedMethod={selectedSearchMethod}
              onMethodChange={handleSearchMethodChange}
            />
          </Box>
        </Paper>

        <div className="app-container">
          <div className="chat-panel">
            <Chat
              messages={messages}
              onSendMessage={handleSendMessage}
              isConnected={isConnected}
            />
          </div>
          <div className="document-panel">
            <DocumentViewer
              document={currentDocument}
              onNext={() => navigateDocument('next')}
              onPrevious={() => navigateDocument('prev')}
              hasMultipleSources={availableSources.length > 1}
              currentIndex={currentDocumentIndex + 1}
              totalSources={availableSources.length}
              cloudfrontDomain={config?.cloudfrontDomain}
            />

            {/* Always show navigation footer, but disable buttons if needed */}
            <div className="document-navigation">
              <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2, p: 1, borderTop: '1px solid #e0e0e0' }}>
                <ButtonGroup variant="outlined" size="small">
                  <Button
                    onClick={() => navigateDocument('prev')}
                    startIcon={<ArrowBackIosNewIcon />}
                    disabled={availableSources.length <= 1}
                  >
                    Prev
                  </Button>
                  <Button disabled>
                    {availableSources.length > 0 ?
                      `${currentDocumentIndex + 1} / ${availableSources.length}` :
                      "0 / 0"}
                  </Button>
                  <Button
                    onClick={() => navigateDocument('next')}
                    endIcon={<ArrowForwardIosIcon />}
                    disabled={availableSources.length <= 1}
                  >
                    Next
                  </Button>
                </ButtonGroup>
              </Box>
            </div>
          </div>
        </div>
      </div>
    </ThemeProvider>
  );
}

export default Layout;