"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { currentUserId, PROJECT_ID, USER_ID } from "./api";

type NavIconName = "dashboard" | "review" | "upload" | "drawings" | "quantities" | "prices" | "approvals" | "history" | "chat";
type NavItem = [string, string, NavIconName];
const navigationGroups: { label: string; items: NavItem[] }[] = [
  { label: "검토", items: [["/", "검토 홈", "dashboard"], ["/review", "확인 요청함", "review"], ["/quantities", "최초 자료 검토", "quantities"], ["/drawings", "설계변경 검토", "drawings"], ["/prices", "신규내역 단가 검토", "prices"]] },
  { label: "자료·승인", items: [["/upload", "자료 업로드·회차", "upload"], ["/approvals", "승인 대기열", "approvals"], ["/history", "검토 이력", "history"]] },
  { label: "도움", items: [["/chat", "검토 챗봇", "chat"]] },
];

function NavIcon({ name }: { name: NavIconName }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (name === "dashboard") return <svg viewBox="0 0 24 24" aria-hidden="true"><rect {...common} x="3" y="3" width="7" height="7" rx="1" /><rect {...common} x="14" y="3" width="7" height="7" rx="1" /><rect {...common} x="3" y="14" width="7" height="7" rx="1" /><rect {...common} x="14" y="14" width="7" height="7" rx="1" /></svg>;
  if (name === "review") return <svg viewBox="0 0 24 24" aria-hidden="true"><rect {...common} x="5" y="3" width="14" height="18" rx="2" /><path {...common} d="M9 3.5h6M8 9h8M8 13h3M8 17l2 2 4-4" /></svg>;
  if (name === "upload") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="M12 16V4M8 8l4-4 4 4M5 14v5h14v-5" /></svg>;
  if (name === "drawings") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="m4 7 8-4 8 4-8 4-8-4Z" /><path {...common} d="m4 12 8 4 8-4M4 17l8 4 8-4" /></svg>;
  if (name === "quantities") return <svg viewBox="0 0 24 24" aria-hidden="true"><rect {...common} x="5" y="3" width="14" height="18" rx="2" /><path {...common} d="M8 7h8M8 11h2M14 11h2M8 15h2M14 15h2M8 19h8" /></svg>;
  if (name === "prices") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="m4 5 9-2 8 8-8 8-9-9V5Z" /><circle {...common} cx="8" cy="8" r="1.2" /></svg>;
  if (name === "approvals") return <svg viewBox="0 0 24 24" aria-hidden="true"><circle {...common} cx="12" cy="12" r="9" /><path {...common} d="m8 12 2.5 2.5L16 9" /></svg>;
  if (name === "history") return <svg viewBox="0 0 24 24" aria-hidden="true"><circle {...common} cx="12" cy="12" r="9" /><path {...common} d="M12 7v5l3 2M4 8V4m0 0h4" /></svg>;
  if (name === "chat") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="M5 5h14v10H9l-4 4V5Z" /><path {...common} d="M8 9h8M8 12h5" /></svg>;
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle {...common} cx="12" cy="8" r="3" /><path {...common} d="M5 21v-2a5 5 0 0 1 10 0v2M17 12h4M19 10v4" /></svg>;
}

export function AppShell({ children, eyebrow, title }: { children: React.ReactNode; eyebrow: string; title: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [userId, setUserId] = useState(USER_ID);
  const [displayName, setDisplayName] = useState("");
  const [department, setDepartment] = useState("");
  const [pinned, setPinned] = useState(false);
  const [dataScope, setDataScope] = useState<string | null>(null);
  useEffect(() => {
    setUserId(currentUserId());
    setDisplayName(window.localStorage.getItem("mvp_display_name") || "");
    setDepartment(window.localStorage.getItem("mvp_department") || "");
    setPinned(window.localStorage.getItem("mvp_sidebar_pinned") === "true");
    setDataScope(new URLSearchParams(window.location.search).get("dataScope"));
  }, []);
  function withDataScope(path: string) {
    if (!dataScope) return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}dataScope=${encodeURIComponent(dataScope)}`;
  }
  function togglePinned() {
    setPinned(current => {
      const next = !current;
      window.localStorage.setItem("mvp_sidebar_pinned", String(next));
      return next;
    });
  }
  function logout() {
    window.localStorage.removeItem("mvp_user_id");
    window.localStorage.removeItem("mvp_display_name");
    window.localStorage.removeItem("mvp_department");
    window.localStorage.removeItem("mvp_roles");
    router.push("/login");
  }
  return <main className="app-shell">
    <aside className={`sidebar ${pinned ? "is-pinned" : ""}`}>
      <div className="brand"><span className="brand-mark">CR</span><div className="brand-copy"><strong>Cost Review</strong><small>공사비 적정성 검토</small></div><button type="button" className="sidebar-toggle" onClick={togglePinned} aria-label={pinned ? "메뉴 고정 해제" : "메뉴 펼쳐 고정"} aria-pressed={pinned} title={pinned ? "메뉴 고정 해제" : "메뉴 펼쳐 고정"}><span aria-hidden="true">{pinned ? "‹" : "›"}</span></button></div>
      <div className="project-context"><span>검토 대상 프로젝트</span><strong>광양5 사무동</strong><small>{PROJECT_ID}</small></div>
      <nav aria-label="검토 화면">
        {navigationGroups.map(group => <div className="nav-group" key={group.label}><span className="nav-group-label">{group.label}</span>{group.items.map(([href, label, icon]) => <Link key={href} href={withDataScope(href)} title={label} className={pathname === href ? "nav-link active" : "nav-link"}><span className="nav-icon"><NavIcon name={icon} /></span><span className="nav-label">{label}</span></Link>)}</div>)}
      </nav>
      <div className="sidebar-note"><strong>자동 확정 금지</strong><p>수량·금액·단가는 담당 부서 승인 전까지 검토 후보로만 표시됩니다.</p></div>
    </aside>
    <section className="content"><header className="page-header"><div><p className="eyebrow">프로젝트 현황 / {eyebrow}</p><h1>{title}</h1></div><div className="header-meta"><span className="status-dot" />승인 대기 유지<span className="user-chip">{displayName || userId} · {department || "검토자"}</span><button type="button" className="logout-button" onClick={logout}>로그아웃</button></div></header>{children}</section>
  </main>;
}

export function PageMessage({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "danger" | "warning" }) { return <div className={`page-message ${tone}`} role="status">{children}</div>; }

export function WorkflowStepper({ current }: { current: "initial" | "change" | "price" }) {
  const [dataScope, setDataScope] = useState<string | null>(null);
  useEffect(() => {
    setDataScope(new URLSearchParams(window.location.search).get("dataScope"));
  }, []);
  const withDataScope = (path: string) => {
    if (!dataScope) return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}dataScope=${encodeURIComponent(dataScope)}`;
  };
  const steps = [{ key: "initial", label: "01 최초 자료", href: "/quantities?sourceSet=기준자료" }, { key: "change", label: "02 설계변경", href: "/drawings" }, { key: "price", label: "03 신규내역 단가", href: "/prices?sourceSet=변경자료" }];
  return <nav className="workflow-stepper" aria-label="핵심 검토 단계">{steps.map(step => <a key={step.key} href={withDataScope(step.href)} className={step.key === current ? "active" : ""} aria-current={step.key === current ? "step" : undefined}>{step.label}</a>)}</nav>;
}

function displayFileName(path?: string) {
  if (!path) return "원본 파일명 확인 필요";
  return path.split(/[\\/]/).pop() || path;
}

export function EvidenceBlock({ evidence }: { evidence?: { file_path?: string; sheet_name?: string; row_ref?: string; location_text?: string; extraction_confidence?: string; evidence_note?: string }[] }) {
  if (!evidence?.length) return <div className="evidence-empty">원본 근거 연결 대기</div>;
  return <div className="evidence-block"><strong>검토 근거</strong>{evidence.slice(0, 3).map((item, index) => <div className="evidence-row" key={`${item.file_path}-${index}`}><span>{displayFileName(item.file_path)}</span><small>시트 {item.sheet_name || "-"} · 행 {item.row_ref || "-"} · 도면 {item.location_text || "-"} · 신뢰도 {item.extraction_confidence || "-"}</small>{item.evidence_note && <small>{item.evidence_note}</small>}</div>)}</div>;
}

export function CandidateBadge({ status, confidence }: { status?: string; confidence?: string }) { return <span className="badge-stack"><span className="status-badge">{status || "검토 대기"}</span>{confidence && <span className="confidence">신뢰도 {confidence}</span>}</span>; }
