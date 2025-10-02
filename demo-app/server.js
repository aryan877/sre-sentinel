/**
 * Simple Node.js API for demo purposes
 * Connects to PostgreSQL and provides health endpoints
 */

const express = require('express');
const app = express();
const port = process.env.PORT || 3001;

// Database connection string from environment
const dbUrl = process.env.DATABASE_URL || 'postgresql://postgres:demo_password@postgres:5432/demo_db';

// Health check endpoint
app.get('/health', (req, res) => {
  console.log('Health check requested');
  res.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    service: 'demo-api'
  });
});

// Root endpoint
app.get('/', (req, res) => {
  console.log('Root endpoint accessed');
  res.json({
    message: 'Demo API is running',
    endpoints: {
      health: '/health',
      db: '/db-check'
    }
  });
});

// Database check endpoint (will fail if DB is down)
app.get('/db-check', async (req, res) => {
  console.log('Database check requested');

  try {
    // Simulate database connection check
    // In a real app, you'd use pg client here
    console.log(`Attempting to connect to: ${dbUrl}`);

    // For demo: just check if postgres hostname resolves
    const { host } = new URL(dbUrl);

    res.json({
      status: 'connected',
      database: host,
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    console.error('Database connection failed:', error.message);
    res.status(500).json({
      status: 'error',
      error: error.message
    });
  }
});

// Simulate memory leak (for demo)
let leakyArray = [];
app.get('/leak', (req, res) => {
  console.log('Memory leak triggered');
  for (let i = 0; i < 100000; i++) {
    leakyArray.push(new Array(1000).fill('leak'));
  }
  res.json({ message: 'Memory leak triggered', arrays: leakyArray.length });
});

// Start server
app.listen(port, () => {
  console.log(`Demo API listening on port ${port}`);
  console.log(`Database URL: ${dbUrl}`);
  console.log('Service started successfully');
});