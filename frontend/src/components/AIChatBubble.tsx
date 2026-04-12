import { useEffect, useMemo, useRef, useState } from "react";
import { MessageCircle, Send, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { sendDashboardChatMessage, sendUnderstandingChatMessage } from "../api/client";
import "./AIChatBubble.css";

export type AIContextPage = "dashboard" | "understanding";
export type AIContextSection =
  | "project_story"
  | "system_map"
  | "data_journey"
  | "key_decisions"
  | "gotchas"
  | "glossary";

interface AIChatBubbleProps {
  projectId: string;
  context: {
    page: AIContextPage;
    section?: AIContextSection;
    data?: unknown;
    projectName?: string;
  };
}

type ChatMessage = { role: "user" | "assistant"; content: string };

const SUGGESTED_QUESTIONS: Record<AIContextPage | AIContextSection, string[]> = {
  dashboard: [
    "What does this project do in simple terms?",
    "What are the main technologies used?",
    "How complex is this codebase?",
  ],
  understanding: [
    "What should I understand first?",
    "Which section should I focus on next?",
    "What part is most important for onboarding?",
  ],
  project_story: [
    "Why was this built this way?",
    "Who would typically use this?",
    "What's the most important part of this system?",
  ],
  system_map: [
    "How do these components communicate?",
    "What happens if the database goes down?",
    "Which component is most critical?",
  ],
  data_journey: [
    "What could go wrong in this flow?",
    "How is authentication handled here?",
    "What happens if a step fails?",
  ],
  key_decisions: [
    "Were there better alternatives?",
    "What problems do these choices solve?",
    "What would you change?",
  ],
  gotchas: [
    "How serious are these issues?",
    "How would I fix the most critical one?",
    "Are there security risks?",
  ],
  glossary: [
    "How are these terms related?",
    "Which concept is most important to understand?",
    "How does this compare to standard patterns?",
  ],
};

function getUnderstandingSectionLabel(section?: AIContextSection): string {
  switch (section) {
    case "project_story":
      return "project story";
    case "system_map":
      return "architecture";
    case "data_journey":
      return "data journey";
    case "key_decisions":
      return "key decisions";
    case "gotchas":
      return "gotchas";
    case "glossary":
      return "glossary";
    default:
      return "documentation";
  }
}

function toUnderstandingBackendSection(section?: AIContextSection): string {
  switch (section) {
    case "project_story":
      return "story";
    case "system_map":
      return "map";
    case "data_journey":
      return "journey";
    case "key_decisions":
      return "decisions";
    case "gotchas":
      return "gotchas";
    case "glossary":
      return "glossary";
    default:
      return "story";
  }
}

export default function AIChatBubble({ projectId, context }: AIChatBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasConversation, setHasConversation] = useState(false);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const lastMessageRef = useRef<HTMLDivElement | null>(null);

  const contextKey = `${context.page}:${context.section ?? "dashboard"}`;
  const subtitle = useMemo(() => {
    if (context.page === "dashboard") {
      return `Ask about ${context.projectName ?? "this project"}`;
    }
    return `Ask about the ${getUnderstandingSectionLabel(context.section)}`;
  }, [context.page, context.projectName, context.section]);

  const initialMessage = useMemo(() => {
    if (context.page === "dashboard") {
      return `I can help explain ${context.projectName ?? "this project"} in plain English.`;
    }
    return `I can answer questions about the ${getUnderstandingSectionLabel(context.section)} section.`;
  }, [context.page, context.projectName, context.section]);

  const suggestions = useMemo(() => {
    if (context.page === "dashboard") {
      return SUGGESTED_QUESTIONS.dashboard;
    }
    return SUGGESTED_QUESTIONS[context.section ?? "project_story"];
  }, [context.page, context.section]);

  useEffect(() => {
    setMessages([{ role: "assistant", content: initialMessage }]);
    setHasConversation(false);
    setInput("");
  }, [contextKey, initialMessage]);

  useEffect(() => {
    if (!messagesRef.current) return;
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages, loading, isOpen]);

  useEffect(() => {
    lastMessageRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  async function sendMessage(raw: string) {
    const text = raw.trim();
    if (!text || loading) return;

    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setHasConversation(true);

    try {
      if (context.page === "dashboard") {
        const payload = nextMessages.filter((m, i) => i !== 0 || m.role !== "assistant");
        const res = await sendDashboardChatMessage(projectId, payload);
        setMessages([...nextMessages, { role: "assistant", content: res.response }]);
      } else {
        const section = toUnderstandingBackendSection(context.section);
        const history = nextMessages.filter((m) => m.role === "user" || m.role === "assistant");
        const res = await sendUnderstandingChatMessage(projectId, section, text, history);
        setMessages([...nextMessages, { role: "assistant", content: res.response }]);
      }
    } catch {
      setMessages([
        ...nextMessages,
        { role: "assistant", content: "I hit an error while checking this section. Please try again." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="ai-chat-shell">
      <div className={`ai-chat-panel ${isOpen ? "open" : ""}`}>
        <div className="ai-chat-head">
          <div>
            <div className="ai-chat-title">AI Architect</div>
            <div className="ai-chat-subtitle">{subtitle}</div>
          </div>
          <button className="ai-chat-close" onClick={() => setIsOpen(false)} aria-label="Minimize chat">
            <X size={16} />
          </button>
        </div>

        <div className="ai-chat-body" ref={messagesRef}>
          {messages.map((m, i) => (
            <div key={`${m.role}-${i}`} className={`ai-chat-msg ${m.role}`}>
              {m.role === "assistant" ? (
                <div className="ai-chat-markdown">
                  <ReactMarkdown>{m.content}</ReactMarkdown>
                </div>
              ) : (
                m.content
              )}
            </div>
          ))}
          {loading && <div className="ai-chat-msg assistant">Thinking...</div>}
          <div ref={lastMessageRef} />
        </div>

        {!hasConversation && (
          <div className="ai-chat-suggestions">
            {suggestions.map((q) => (
              <button key={q} className="ai-chat-pill" onClick={() => void sendMessage(q)}>
                {q}
              </button>
            ))}
          </div>
        )}

        <form
          className="ai-chat-input-wrap"
          onSubmit={(e) => {
            e.preventDefault();
            void sendMessage(input);
          }}
        >
          <input
            className="ai-chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything about this codebase..."
            disabled={loading}
          />
          <button className="ai-chat-send" type="submit" disabled={loading || !input.trim()}>
            <Send size={14} />
          </button>
        </form>
      </div>

      <button
        className={`ai-chat-fab ${!isOpen ? "pulse" : ""}`}
        onClick={() => setIsOpen((v) => !v)}
        aria-label="Open AI chat"
      >
        <MessageCircle size={22} />
      </button>
    </div>
  );
}
