"use client";

import React, { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import PoeEntityChip from "./PoeEntityChip";
import "./chat-markdown.css";

export interface EntityMention {
  start: number;
  end: number;
  label: string;
  name_en: string;
  type: string;
}

const MARKER_RE = /⟦poe:([^|]+)\|([^|]+)\|([^⟧]+)⟧/g;

function apiUrl() {
  if (typeof window === "undefined") return "http://localhost:8000";
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

function applyMentionMarkers(raw: string, mentions: EntityMention[]): string {
  const sorted = [...mentions]
    .filter((m) => m.end > m.start && m.start >= 0 && m.end <= raw.length)
    .sort((a, b) => b.start - a.start);
  let s = raw;
  for (const m of sorted) {
    const token = `⟦poe:${m.label}|${m.name_en}|${m.type}⟧`;
    s = s.slice(0, m.start) + token + s.slice(m.end);
  }
  return s;
}

function parseEntityMarkers(text: string): React.ReactNode {
  MARKER_RE.lastIndex = 0;
  if (!MARKER_RE.test(text)) {
    MARKER_RE.lastIndex = 0;
    return text;
  }
  MARKER_RE.lastIndex = 0;
  const parts: React.ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  let idx = 0;
  while ((match = MARKER_RE.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    parts.push(
      <PoeEntityChip
        key={`chip-${match.index}-${idx}`}
        label={match[1]}
        nameEn={match[2]}
        entityType={match[3]}
      />,
    );
    last = match.index + match[0].length;
    idx += 1;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.length === 1 ? parts[0] : <>{parts}</>;
}

function renderChips(children: React.ReactNode): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") return parseEntityMarkers(child);
    if (React.isValidElement(child)) {
      const props = child.props as { children?: React.ReactNode };
      if (props.children != null) {
        return React.cloneElement(child, {}, renderChips(props.children));
      }
    }
    return child;
  });
}

function normalizeContent(content: string): string {
  return content.replace(/\[资料\]/g, "`资料`").replace(/\[推测\]/g, "**[推测]**");
}

interface ChatMarkdownProps {
  content: string;
  /** Only assistant answers — never user input. */
  enableEntityChips?: boolean;
}

export default function ChatMarkdown({ content, enableEntityChips = false }: ChatMarkdownProps) {
  const [mentions, setMentions] = useState<EntityMention[]>([]);

  const normalized = useMemo(() => normalizeContent(content), [content]);

  useEffect(() => {
    if (!enableEntityChips || !normalized.trim()) {
      setMentions([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        const res = await fetch(`${apiUrl()}/api/entities/mentions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: normalized }),
        });
        if (res.ok) {
          const data = (await res.json()) as { mentions?: EntityMention[] };
          setMentions(data.mentions ?? []);
        }
      } catch {
        /* ignore */
      }
    }, 320);
    return () => window.clearTimeout(timer);
  }, [normalized, enableEntityChips]);

  const markdownSource = useMemo(() => {
    if (!enableEntityChips || !mentions.length) return normalized;
    return applyMentionMarkers(normalized, mentions);
  }, [normalized, mentions, enableEntityChips]);

  const wrapChips = (children: React.ReactNode) =>
    enableEntityChips ? renderChips(children) : children;

  const components: Components = useMemo(
    () => ({
      p: ({ children }) => <p className="md-p">{wrapChips(children)}</p>,
      li: ({ children }) => <li className="md-li">{wrapChips(children)}</li>,
      strong: ({ children }) => <strong className="md-bold">{wrapChips(children)}</strong>,
      em: ({ children }) => <em className="md-em">{wrapChips(children)}</em>,
      h1: ({ children }) => <h2 className="md-h1">{wrapChips(children)}</h2>,
      h2: ({ children }) => <h2 className="md-h2">{wrapChips(children)}</h2>,
      h3: ({ children }) => <h3 className="md-h3">{wrapChips(children)}</h3>,
      h4: ({ children }) => <h4 className="md-h4">{wrapChips(children)}</h4>,
      blockquote: ({ children }) => <blockquote className="md-quote">{wrapChips(children)}</blockquote>,
      hr: () => <hr className="md-hr" />,
      code: ({ children }) => <code className="md-code">{children}</code>,
      a: ({ href, children }) => (
        <a href={href} target="_blank" rel="noreferrer" className="md-link">
          {wrapChips(children)}
        </a>
      ),
      table: ({ children }) => (
        <div className="md-table-wrap">
          <table className="md-table">{children}</table>
        </div>
      ),
      thead: ({ children }) => <thead className="md-thead">{children}</thead>,
      tbody: ({ children }) => <tbody>{children}</tbody>,
      tr: ({ children }) => <tr className="md-tr">{children}</tr>,
      th: ({ children }) => <th className="md-th">{wrapChips(children)}</th>,
      td: ({ children }) => <td className="md-td">{wrapChips(children)}</td>,
    }),
    [enableEntityChips],
  );

  return (
    <div className="chat-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdownSource}
      </ReactMarkdown>
    </div>
  );
}
