import pathlib

path = pathlib.Path("frontend/src/app/page.tsx")
text = path.read_text(encoding="utf-8")

old = '''import { useState, useEffect, useCallback } from "react";
'''
new = '''import { useState, useEffect, useCallback, useRef } from "react";
'''

if old not in text:
    raise SystemExit("react import block not found")
text = text.replace(old, new)

old_block = '''  const [pobValid, setPobValid] = useState<boolean | null>(null);
  
  const loadHistory = useCallback(() => {
    setHistory(getLocalBuildHistory().map(toHistorySummary));
  }, []);
'''
new_block = '''  const [pobValid, setPobValid] = useState<boolean | null>(null);
  const pollAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      pollAbortRef.current?.abort();
    };
  }, []);
  
  const loadHistory = useCallback(() => {
    setHistory(getLocalBuildHistory().map(toHistorySummary));
  }, []);
'''

if old_block not in text:
    raise SystemExit("state block not found")
text = text.replace(old_block, new_block)

old_poll = '''      while (!isDone && attempts < maxAttempts) {
        attempts++;
        const fullRes = await fetchWithError(`${apiUrl()}/api/builds/${buildId}`);
        
        const fullData = await fullRes.json();
        
        if (fullData.status === "done") {
          setResult(fullData);
          addLocalBuildHistory({ id: buildId, status: "done", build: fullData.build || {}, savedAt: new Date().toISOString() });
          loadHistory();
          isDone = true;
        } else if (fullData.status === "failed") {
          throw { message: "AI 攻略生成失败，请重试" };
        } else {
          // Still pending, wait 2 seconds and show temporary result (without homework)
          setResult(fullData);
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      }
'''
new_poll = '''      pollAbortRef.current = new AbortController();
      while (!isDone && attempts < maxAttempts) {
        attempts++;
        try {
          const fullRes = await fetchWithError(`${apiUrl()}/api/builds/${buildId}`, {
            signal: pollAbortRef.current.signal,
          });
          const fullData = await fullRes.json();
          if (fullData.status === "done") {
            setResult(fullData);
            addLocalBuildHistory({ id: buildId, status: "done", build: fullData.build || {}, savedAt: new Date().toISOString() });
            loadHistory();
            isDone = true;
          } else if (fullData.status === "failed") {
            throw { message: "AI 攻略生成失败，请重试" };
          } else {
            setResult(fullData);
          }
        } catch (pollErr) {
          if ((pollErr as any)?.name === "AbortError") {
            break;
          }
          const wait = Math.min(1000 * Math.pow(2, attempts - 1), 8000);
          await new Promise((resolve) => setTimeout(resolve, wait));
          if (attempts >= maxAttempts) {
            throw { message: "AI 生成超时，请稍后在本机历史中查看" };
          }
          continue;
        }
        if (!isDone) {
          const wait = Math.min(1000 * Math.pow(2, attempts - 1), 8000);
          await new Promise((resolve) => setTimeout(resolve, wait));
        }
      }
      pollAbortRef.current = null;
'''

if old_poll not in text:
    raise SystemExit("polling block not found")
text = text.replace(old_poll, new_poll)

old_timeout = '''      if (!isDone) {
        throw { message: "AI 生成超时，请稍后在本机历史中查看" };
      }

      loadHistory();
'''
new_timeout = '''      if (!isDone) {
        throw { message: "AI 生成超时，请稍后在本机历史中查看" };
      }

      loadHistory();
    } catch (err: unknown) {
      if (pollAbortRef.current) {
        pollAbortRef.current = null;
      }
      if (err && typeof err === "object" && "message" in err) {
        setError(err as { message: string; reason?: string });
      } else {
        setError({ message: err instanceof Error ? err.message : "未知错误" });
      }
    } finally {
      pollAbortRef.current?.abort();
      pollAbortRef.current = null;
      setLoading(false);
      setLoadingStep("");
    }
'''

# The original already has try/catch/finally, we need to be careful not to duplicate.
# We'll only replace the timeout + following loadHistory + existing catch/finally block.
if old_timeout not in text:
    raise SystemExit("timeout block not found")
text = text.replace(old_timeout, new_timeout)

path.write_text(text, encoding="utf-8")
