import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { MessageCircle, Send, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { API_BASE } from "../api/client";
import "./AIChatBubble.css";

export type AIContextPage =
  | "dashboard"
  | "understanding"
  | "feature_map"
  | "api_explorer"
  | "sequence_diagram";
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
    pageContext?: Record<string, unknown> | null;
    resetKey?: string;
  };
  suggestedQuestions?: string[];
}

type ChatMessage = { role: "user" | "assistant"; content: string };
type AskCopilotDetail = {
  question: string;
  pageContext?: Record<string, unknown> | null;
};
type AskCopilotButtonProps = {
  onAsk: () => void;
  inline?: boolean;
  className?: string;
  style?: CSSProperties;
};
const ASK_COPILOT_EVENT = "ai-chat:ask";

const SUGGESTED_QUESTIONS: Record<AIContextPage | AIContextSection, string[]> = {
  dashboard: [
    "Where should I start reading this codebase?",
    "What is the riskiest part of this project?",
    "What external services does this project depend on?",
    "What are the main entry points?",
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
  feature_map: [
    "Which features are most tightly coupled?",
    "Which feature is safest to modify?",
    "What files are shared across the most features?",
    "Which feature has the most external dependencies?",
  ],
  api_explorer: [
    "Which route is most complex?",
    "Which routes touch the database?",
    "Are there any routes without authentication?",
  ],
  sequence_diagram: [
    "What error handling exists in this flow?",
    "Which step is most likely to fail?",
    "How many database calls does this route make?",
    "What would a junior developer misunderstand about this flow?",
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

function getContextSubtitle(context: AIChatBubbleProps["context"]) {
  if (context.page === "dashboard") {
    return `Ask about ${context.projectName ?? "this project"}`;
  }
  if (context.page === "understanding") {
    return `Ask about the ${getUnderstandingSectionLabel(context.section)}`;
  }
  if (context.page === "feature_map") {
    const featureName = typeof context.pageContext?.["selected_feature"] === "string"
      ? context.pageContext["selected_feature"]
      : null;
    return featureName ? `Ask about ${featureName}` : "Ask about the feature map";
  }
  if (context.page === "api_explorer") {
    const routeMethod = typeof context.pageContext?.["route_method"] === "string"
      ? context.pageContext["route_method"]
      : null;
    const routePath = typeof context.pageContext?.["route_path"] === "string"
      ? context.pageContext["route_path"]
      : null;
    return routeMethod && routePath ? `Ask about ${routeMethod} ${routePath}` : "Ask about the API explorer";
  }
  if (context.page === "sequence_diagram") {
    const routeMethod = typeof context.pageContext?.["route_method"] === "string"
      ? context.pageContext["route_method"]
      : null;
    const routePath = typeof context.pageContext?.["route_path"] === "string"
      ? context.pageContext["route_path"]
      : null;
    return routeMethod && routePath ? `Ask about ${routeMethod} ${routePath}` : "Ask about this request flow";
  }
  return "Ask about this codebase";
}

function getInitialMessage(context: AIChatBubbleProps["context"]) {
  if (context.page === "dashboard") {
    return `I can help explain ${context.projectName ?? "this project"} in plain English.`;
  }
  if (context.page === "understanding") {
    return `I can answer questions about the ${getUnderstandingSectionLabel(context.section)} section.`;
  }
  if (context.page === "feature_map") {
    const featureName = typeof context.pageContext?.["selected_feature"] === "string"
      ? context.pageContext["selected_feature"]
      : null;
    return featureName
      ? `I can help you understand how ${featureName} fits into the rest of the codebase.`
      : "I can help you understand how the major features connect and where change risk lives.";
  }
  if (context.page === "api_explorer") {
    const routeMethod = typeof context.pageContext?.["route_method"] === "string"
      ? context.pageContext["route_method"]
      : null;
    const routePath = typeof context.pageContext?.["route_path"] === "string"
      ? context.pageContext["route_path"]
      : null;
    return routeMethod && routePath
      ? `I can explain what happens in ${routeMethod} ${routePath} and how it fits into the API.`
      : "I can help you inspect route complexity, data access, and API behavior.";
  }
  if (context.page === "sequence_diagram") {
    return "I can walk through this execution flow step by step and call out the risky parts.";
  }
  return "I can help explain this codebase in plain English.";
}

function getBackendSection(context: AIChatBubbleProps["context"]) {
  if (context.page === "understanding") {
    return toUnderstandingBackendSection(context.section);
  }
  return context.page;
}

async function postChat<T>(url: string, payload: Record<string, unknown>, fallbackMessage: string): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail || body?.message || fallbackMessage);
  }
  return body as T;
}

export function requestAIChatPrompt(detail: AskCopilotDetail) {
  if (typeof window === "undefined") {
    return;
  }

  window.dispatchEvent(new CustomEvent<AskCopilotDetail>(ASK_COPILOT_EVENT, { detail }));
}

export function AskCopilotButton({ onAsk, inline = false, className = "", style }: AskCopilotButtonProps) {
  return (
    <button
      type="button"
      className={`ask-copilot-button ${inline ? "inline" : "corner"} ${className}`.trim()}
      title="Ask Copilot about this"
      aria-label="Ask Copilot about this"
      onClick={(event) => {
        event.stopPropagation();
        onAsk();
      }}
      style={style}
    >
      <span aria-hidden="true">💬</span>
    </button>
  );
}

export default function AIChatBubble({ projectId, context, suggestedQuestions = [] }: AIChatBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasConversation, setHasConversation] = useState(false);
  const [overridePageContext, setOverridePageContext] = useState<Record<string, unknown> | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const lastMessageRef = useRef<HTMLDivElement | null>(null);

  const contextKey = useMemo(
    () =>
      [
        context.page,
        context.section ?? "",
        context.resetKey ?? "",
        JSON.stringify(context.pageContext ?? {}),
        suggestedQuestions.join("|"),
      ].join(":"),
    [context.page, context.pageContext, context.resetKey, context.section, suggestedQuestions],
  );
  const subtitle = useMemo(() => getContextSubtitle(context), [context]);

  const initialMessage = useMemo(() => getInitialMessage(context), [context]);
  const effectivePageContext = overridePageContext ?? context.pageContext ?? null;

  const suggestions = useMemo(() => {
    if (suggestedQuestions.length > 0) {
      return suggestedQuestions;
    }
    if (context.page === "dashboard") {
      return SUGGESTED_QUESTIONS.dashboard;
    }
    if (context.page === "understanding") {
      return SUGGESTED_QUESTIONS[context.section ?? "project_story"];
    }
    return SUGGESTED_QUESTIONS[context.page];
  }, [context.page, context.section, suggestedQuestions]);

  useEffect(() => {
    setMessages([{ role: "assistant", content: initialMessage }]);
    setHasConversation(false);
    setInput("");
    setOverridePageContext(null);
  }, [contextKey, initialMessage]);

  useEffect(() => {
    const handleAsk = (event: Event) => {
      const customEvent = event as CustomEvent<AskCopilotDetail>;
      const detail = customEvent.detail;
      if (!detail?.question) {
        return;
      }

      const nextPageContext = detail.pageContext ?? null;
      setOverridePageContext(nextPageContext);
      setIsOpen(true);
      setInput(detail.question);
      window.setTimeout(() => {
        void sendMessage(detail.question, nextPageContext);
      }, 0);
    };

    window.addEventListener(ASK_COPILOT_EVENT, handleAsk as EventListener);
    return () => {
      window.removeEventListener(ASK_COPILOT_EVENT, handleAsk as EventListener);
    };
  });

  useEffect(() => {
    if (!messagesRef.current) return;
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages, loading, isOpen]);

  useEffect(() => {
    lastMessageRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  async function sendMessage(raw: string, pageContextOverride?: Record<string, unknown> | null) {
    const text = raw.trim();
    if (!text || loading) return;
    const requestPageContext = pageContextOverride ?? effectivePageContext;

    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setHasConversation(true);

    try {
      if (context.page === "dashboard") {
        const payload = nextMessages.filter((m, i) => i !== 0 || m.role !== "assistant");
        const res = await postChat<{ response: string }>(
          `${API_BASE}/projects/${projectId}/dashboard/chat`,
          {
            messages: payload,
            page_context: requestPageContext,
          },
          "Failed to send chat message",
        );
        setMessages([...nextMessages, { role: "assistant", content: res.response }]);
      } else {
        const section = getBackendSection(context);
        const history = nextMessages.filter((m) => m.role === "user" || m.role === "assistant");
        const res = await postChat<{ response: string }>(
          `${API_BASE}/projects/${projectId}/understanding/chat`,
          {
            section,
            message: text,
            history,
            page_context: requestPageContext,
          },
          "Failed to send understanding chat message",
        );
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
