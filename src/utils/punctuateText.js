// punctuateText.js
// --------------------------------------------------
// Utility for punctuating raw transcript text using
// Hugging Face's punctuation model via REST API.
// --------------------------------------------------

const HUGGINGFACE_API_TOKEN = process.env.REACT_APP_HUGGINGFACE_API_TOKEN || '';

/**
 * Punctuates raw transcript text using Hugging Face's fullstop model.
 *
 * @param {string} rawText - The transcript text without punctuation.
 * @returns {Promise<string>} - A promise resolving to punctuated text.
 */
export async function punctuateText(rawText) {
  const apiUrl = "https://api-inference.huggingface.co/models/oliverguhr/fullstop-punctuation-multilang-large";

  try {
    const response = await fetch(apiUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${HUGGINGFACE_API_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ inputs: rawText }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      console.error("❌ Hugging Face API Error:", errorData);
      throw new Error("Failed to punctuate transcript.");
    }

    const data = await response.json();

    if (Array.isArray(data) && data[0]?.generated_text) {
      return data[0].generated_text.trim();
    }

    console.warn("⚠️ Unexpected Hugging Face API response format:", data);
    return rawText; 
  } catch (error) {
    console.error("❌ Punctuation API request failed:", error.message);
    return rawText; 
  }
}
