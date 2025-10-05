/**
 * Simple Node.js API for demo purposes
 * Connects to PostgreSQL and provides health endpoints
 */

const express = require("express");
const { Pool } = require("pg");
const app = express();
const port = process.env.PORT || 3001;

// Database connection string from environment
const dbUrl =
  process.env.DATABASE_URL ||
  "postgresql://postgres:demo_password@postgres:5432/demo_db";

// Create PostgreSQL pool
const pool = new Pool({
  connectionString: dbUrl,
  max: 20,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 2000,
});

// Test database connection on startup
pool.query("SELECT NOW()", (err) => {
  if (err) {
    console.error("Database connection failed on startup:", err.message);
    console.log("Service will continue, but database operations will fail");
  } else {
    console.log("Database connected successfully");
  }
});

// Health check endpoint
app.get("/health", (req, res) => {
  console.log("Health check requested");
  res.json({
    status: "healthy",
    timestamp: new Date().toISOString(),
    service: "demo-api",
  });
});

// Root endpoint
app.get("/", (req, res) => {
  console.log("Root endpoint accessed");
  res.json({
    message: "Demo API is running",
    endpoints: {
      health: "/health",
      db: "/db-check",
    },
  });
});

// Database check endpoint (will fail if DB is down)
app.get("/db-check", async (req, res) => {
  console.log("Database check requested");

  try {
    console.log(`Attempting to connect to: ${dbUrl}`);
    const result = await pool.query(
      "SELECT NOW() as current_time, version() as version"
    );

    res.json({
      status: "connected",
      database: "postgres",
      timestamp: result.rows[0].current_time,
      version: result.rows[0].version,
    });
  } catch (error) {
    console.error("Database connection failed:", error.message);
    console.error("Full error:", error);
    res.status(500).json({
      status: "error",
      error: error.message,
      code: error.code,
    });
  }
});

// Add an endpoint that continuously checks DB (to generate errors when DB is down)
setInterval(async () => {
  try {
    await pool.query("SELECT 1");
  } catch (error) {
    console.error(
      `[${new Date().toISOString()}] Database health check failed: ${
        error.message
      }`
    );
    console.error(`Error code: ${error.code || "UNKNOWN"}`);
  }
}, 5000); // Check every 5 seconds

// Simulate memory leak (for demo)
let leakyArray = [];
app.get("/leak", (req, res) => {
  console.log("Memory leak triggered");
  for (let i = 0; i < 100000; i++) {
    leakyArray.push(new Array(1000).fill("leak"));
  }
  res.json({ message: "Memory leak triggered", arrays: leakyArray.length });
});

// Start server
app.listen(port, () => {
  console.log(`Demo API listening on port ${port}`);
  console.log(`Database URL: ${dbUrl}`);
  console.log("Service started successfully");
});
