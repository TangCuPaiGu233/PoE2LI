"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
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

function apiUrl() {
  if (typeof window === "undefined") return "http://localhost:8000";
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

function mentionize(text: string, mentions: EntityMention[]): React.ReactNode[] {
  if (!text || !mentions.length) return [text];
  const sorted = mentions
    .filter((m) => m.end > m.start)
    .sort((a, b) => a.start - b.start);
  const out: React.ReactNode[] = [];
  let cursor = 0;
  sorted.forEach((m, idx) => {
    if (m.start < cursor) return;
    if (m.start > cursor) out.push(text.slice(cursor, m.start));
    out.push(
      <PoeEntityChip
        key={`${m.start}-${m.label}-${idx}`}
        label={m.label}
        nameEn={m.name_en}
        entityType={m.type}
      />,
    );
    cursor = m.end;
  });
  if (cursor < text.length) out.push(text.slice(cursor));
  return out.length ? out : [text];
}

function processChildren(children: React.ReactNode, mentions: EntityMention[]): React.ReactNode {
  if (typeof children === "string") return mentionize(children, mentions);
  if (Array.isArray(children)) {
    return children.map((child, i) => (
      <React.Fragment key={i}>{processChildren(child, mentions)}</React.Fragment>
    ));
  }
  return children;
}

interface ChatMarkdownProps {
  content: string;
}

export default function ChatMarkdown({ content }: ChatMarkdownProps) {
  const [mentions, setMentions] = useState<EntityMention[]>([]);

  useEffect(() => {
    if (!content.trim()) {
      setMentions([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        const res = await fetch(`${apiUrl()}/api/entities/mentions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: content }),
        });
        if (res.ok) {
          const data = (await res.json()) as { mentions?: EntityMention[] };
          setMentions(data.mentions ?? []);
        }
      } catch {
        /* ignore */
      }
    }, 280);
    return () => window.clearTimeout(timer);
  }, [content]);

  const withMentions = useCallback(
    (children: React.ReactNode) => processChildren(children, mentions),
    [mentions],
  );

  const components: Components = useMemo(
    () => ({
      p: ({ children }) => <p className="md-p">{withMentions(children)}</p>,
      li: ({ children }) => <li className="md-li">{withMentions(children)}</li>,
      strong: ({ children }) => <strong className="md-bold">{withMentions(children)}</strong>,
      em: ({ children }) => <em className="md-em">{withMentions(children)}</em>,
      h1: ({ children }) => <h2 className="md-h1">{withMentions(children)}</h2>,
      h2: ({ children }) => <h2 className="md-h2">{withMentions(children)}</h2>,
      h3: ({ children }) => <h3 className="md-h3">{withMentions(children)}</h3>,
      h4: ({ children }) => <h4 className="md-h4">{withMentions(children)}</h4>,
      blockquote: ({ children }) => <blockquote className="md-quote">{children}</blockquote>,
      hr: () => <hr className="md-hr" />,
      code: ({ children }) => <code className="md-code">{children}</code>,
      a: ({ href, children }) => (
        <a href={href} target="_blank" rel="noreferrer" className="md-link">
          {children}
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
      th: ({ children }) => <th className="md-th">{withMentions(children)}</th>,
      td: ({ children }) => <td className="md-td">{withMentions(children)}</td>,
    }),
    [withMentions],
  );

  const normalized = content
    .replace(/\[资料\]/g, "`资料`")
    .replace(/\[推测\]/g, "**[推测]**");

  return (
    <div className="chat-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
