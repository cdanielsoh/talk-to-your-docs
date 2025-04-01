// src/websocket.js
let socket = null;
let messageCallback = null;

export const connectWebSocket = () => {
  const wsUrl = process.env.NODE_ENV === 'production' 
    ? `wss://${window.location.host}/chat`
    : 'wss://dxvuqkmng0.execute-api.us-west-2.amazonaws.com';

  socket = new WebSocket(wsUrl);

  socket.onopen = () => {
    console.log('WebSocket connection established');
  };

  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    messageCallback && messageCallback(data);
  };

  socket.onclose = () => {
    console.log('WebSocket connection closed');
    setTimeout(connectWebSocket, 5000); // Reconnect after 5 seconds
  };
};

export const registerMessageHandler = (callback) => {
  messageCallback = callback;
};

export const sendChatMessage = (message) => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({
      action: 'sendMessage',
      content: message
    }));
  }
};
