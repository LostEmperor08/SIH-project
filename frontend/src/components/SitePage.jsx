import { ArrowLeft, ArrowRight, CheckCircle2, Globe2, LockKeyhole, Network, ScanSearch, Shield, Sparkles, Workflow } from "lucide-react";

const pages = {
  about: { eyebrow: "About Chakravyuh", title: "The operating layer for modern cyber investigations.", intro: "Built for the teams who turn the first reported wallet into the first actionable lead.", icon: Shield },
  services: { eyebrow: "Platform capabilities", title: "Every investigation signal, in one accountable system.", intro: "A focused set of tools for tracing, attribution, evidence, and action across the full case lifecycle.", icon: Workflow },
  industries: { eyebrow: "Crime patterns", title: "Designed for the complexity of digital financial crime.", intro: "From investment scams to organized laundering networks, the system adapts to the behavior behind the address.", icon: Network },
  insights: { eyebrow: "Field intelligence", title: "A clearer view of what moves money.", intro: "Practical briefings on wallet behavior, cross-chain movement, VASP attribution, and evidence readiness.", icon: Sparkles },
  careers: { eyebrow: "Join the mission", title: "Build infrastructure that helps stop the fraud.", intro: "Work across blockchain intelligence, product design, and public-sector technology with a team that cares about outcomes.", icon: Globe2 },
  contact: { eyebrow: "Connect with I4C", title: "Bring your investigation workflow into focus.", intro: "Tell us what your team needs to trace faster, preserve better, and act with confidence.", icon: ScanSearch },
};

export function SitePage({ page, onNavigate }) {
  const content = pages[page];
  const Icon = content.icon;
  return (
    <div className="site-page">
      <header className="landing-nav"><button type="button" className="brand-lockup" onClick={() => onNavigate("landing")}><span className="brand-mark"><Shield size={18} /></span><span><b>CHAKRAVYUH</b><small>I4C · NATIONAL ATTRIBUTION</small></span></button><nav className="landing-links site-nav-links">{Object.keys(pages).map((id) => <button type="button" className={page === id ? "landing-link-active" : ""} key={id} onClick={() => onNavigate(id)}>{id}</button>)}</nav><div className="landing-actions"><button type="button" className="text-btn" onClick={() => onNavigate("login")}>Sign in</button><button type="button" className="primary-btn" onClick={() => onNavigate("signup")}>Request access <ArrowRight size={14} /></button></div></header>
      <main className="site-page-main">
        <div className="site-page-heading parallax-layer"><div className="eyebrow"><Icon size={14} /> {content.eyebrow}</div><h1>{content.title}</h1><p>{content.intro}</p><button type="button" className="primary-btn primary-btn-large" onClick={() => onNavigate("signup")}>Start an investigation <ArrowRight size={16} /></button></div>
        <div className="site-page-grid">{["Real-time intelligence", "Explainable decisions", "Court-ready evidence"].map((title, index) => <article className="glass-panel site-feature scroll-reveal" key={title}><span className="site-feature-number">0{index + 1}</span><h2>{title}</h2><p>{["Map fund flows across chains, protocols, and intermediary wallets without leaving the case workspace.", "Translate graph signals into attribution confidence, risk categories, and next-best investigative actions.", "Preserve hashes, timestamps, classifications, and notices in a consistent chain of custody."][index]}</p><CheckCircle2 size={16} /></article>)}</div>
        <section className="site-page-band glass-panel"><div><div className="eyebrow"><LockKeyhole size={13} /> Secure by design</div><h2>Make the next move<br /><span>with evidence.</span></h2></div><p>Frontend demo mode is ready for your backend APIs. Connect NCRP, SAHYOG, indexing services, and agency identity when the integration layer is available.</p></section>
      </main>
      <footer className="landing-footer"><button type="button" className="back-link" onClick={() => onNavigate("landing")}><ArrowLeft size={14} /> Back to overview</button><span>Ministry of Home Affairs · CIS Division</span></footer>
    </div>
  );
}
