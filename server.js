const express = require("express");
const cors = require("cors");
const multer = require("multer");
const Tesseract = require("tesseract.js");
const Groq = require("groq-sdk");
require("dotenv").config();

const app = express();

app.use(cors());
app.use(express.json());

// ================= GROQ =================
const groq = new Groq({
  apiKey: process.env.GROQ_API_KEY,
});

// ================= STORAGE =================
const storage = multer.diskStorage({
  destination: function (req, file, cb) {
    cb(null, "uploads/");
  },
  filename: function (req, file, cb) {
    cb(null, Date.now() + "-" + file.originalname);
  },
});

const upload = multer({ storage: storage });

// ================= ROUTES =================

app.get("/", (req, res) => {
  res.send("Server is running 🚀");
});

app.post("/upload", upload.single("file"), async (req, res) => {
  try {
    const filePath = req.file.path;

    // ===== OCR =====
    const result = await Tesseract.recognize(filePath, "eng");
    const extractedText = result.data.text;

    console.log("OCR TEXT:", extractedText);

    // ===== GROQ =====
    const chatCompletion = await groq.chat.completions.create({
      model: "llama-3.1-8b-instant",
      temperature: 0, // IMPORTANT: makes output more stable
      messages: [
        {
          role: "system",
          content:
            "You are a strict JSON generator. You ONLY return valid JSON. No explanation. No markdown.",
        },
        {
          role: "user",
          content: `
Extract the following and return ONLY valid JSON:

{
  "summary": "",
  "name": "",
  "total_amount": "",
  "date": "",
  "sentiment": ""
}

Text:
${extractedText}
          `,
        },
      ],
    });

    let aiOutput = chatCompletion.choices[0].message.content;

    console.log("AI RAW OUTPUT:", aiOutput);

    // ===== CLEAN OUTPUT =====
    aiOutput = aiOutput
      .replace(/```json/g, "")
      .replace(/```/g, "")
      .trim();

    // ===== SAFE PARSE =====
    let parsedData;

    try {
      parsedData = JSON.parse(aiOutput);
    } catch (err) {
      parsedData = {
        error: "Invalid JSON from AI",
        rawOutput: aiOutput,
      };
    }

    res.json({
      message: "AI Processing complete 🚀",
      data: parsedData,
    });

  } catch (error) {
    console.error("FULL ERROR:", error);

    res.status(500).json({
      error: "Processing failed ❌",
      details: error.message,
    });
  }
});

// ================= SERVER =================
const PORT = 5000;

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
