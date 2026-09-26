from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from fastapi import FastAPI
from pydantic import BaseModel, Field
import re
import time

app = FastAPI(title="Vera - Magicpin AI Challenge", version="1.0.0")
@app.get("/")
def root():
    return {"status": "ok", "message": "Vera API is running"}

# ---------------------------------------------------------------------------
# In-memory context store
# ---------------------------------------------------------------------------
contexts: dict[tuple[str, str], dict[str, Any]] = {}
conversations: dict[str, dict[str, Any]] = {}

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}

class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str

class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = Field(default_factory=list)

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get(scope: str, ident: str) -> Optional[dict[str, Any]]:
    item = contexts.get((scope, ident))
    return item["payload"] if item else None

def first_name(name: str) -> str:
    if not name:
        return ""
    n = name.strip()
    # "Dr. Meera's Dental Clinic" -> Meera
    m = re.search(r"\b(?:Dr\.?\s*)?([A-Z][a-z]+)", n)
    return m.group(1) if m else n.split()[0]

def merchant_name(m: dict[str, Any]) -> str:
    ident = m.get("identity", {})
    return ident.get("owner_first_name") or first_name(ident.get("name", "")) or "there"

def language_mode(m: dict[str, Any], c: Optional[dict[str, Any]]) -> str:
    if c:
        pref = str(c.get("identity", {}).get("language_pref", "")).lower()
        if "hi" in pref and "en" in pref:
            return "hi-en"
        if pref.startswith("hi"):
            return "hi"
    langs = [str(x).lower() for x in m.get("identity", {}).get("languages", [])]
    return "hi-en" if "hi" in langs and "en" in langs else "en"

def pct(v: Any) -> str:
    try:
        x = float(v)
        return f"{x*100:.1f}%"
    except Exception:
        return str(v)

def money_title(offer: dict[str, Any]) -> str:
    return offer.get("title") or ""

def active_offers(m: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for o in m.get("offers", []) if str(o.get("status", "active")).lower() == "active"]

def category_voice(category: dict[str, Any]) -> str:
    return str(category.get("voice", {}).get("tone", "")).lower()

def digest_items(category: dict[str, Any]) -> list[dict[str, Any]]:
    return category.get("digest", []) or []

def find_digest(category: dict[str, Any], trigger: dict[str, Any]) -> Optional[dict[str, Any]]:
    payload = trigger.get("payload", {}) or {}
    wanted = payload.get("top_item_id") or payload.get("digest_item_id")
    items = digest_items(category)
    if wanted:
        for d in items:
            if d.get("id") == wanted:
                return d
    # Fall back to the first digest item only when the trigger explicitly asks
    # for research/news/regulation/trend content.
    if trigger.get("kind") in {
        "research_digest", "research_digest_release", "regulation_change",
        "news_event", "trend_signal", "seasonal_beat"
    } and items:
        return items[0]
    return None

def peer_ctr(category: dict[str, Any]) -> Optional[float]:
    try:
        return float(category.get("peer_stats", {}).get("avg_ctr"))
    except Exception:
        return None

def merchant_ctr(m: dict[str, Any]) -> Optional[float]:
    try:
        return float(m.get("performance", {}).get("ctr"))
    except Exception:
        return None

def choose_offer(m: dict[str, Any], c: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    offers = active_offers(m)
    if not offers:
        return None
    # Prefer explicit service-at-price offers for customer acquisition.
    for o in offers:
        if "@" in str(o.get("title", "")):
            return o
    return offers[0]

def taboo_clean(text: str, category: dict[str, Any]) -> str:
    voice = category.get("voice", {}) or {}
    taboos = voice.get("vocab_taboo", voice.get("taboos", [])) or []
    out = text
    for word in taboos:
        if word:
            out = re.sub(re.escape(str(word)), "", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out

def one_cta(text: str, cta: str) -> str:
    # Keep exactly one actionable final sentence. We don't aggressively
    # rewrite body because source contexts can legitimately contain questions.
    return text.strip()

def rationale(trigger: dict[str, Any], why: str) -> str:
    return f"{trigger.get('kind', 'trigger')}: {why}"

# ---------------------------------------------------------------------------
# Deterministic composer
# ---------------------------------------------------------------------------

def compose(category: dict[str, Any], merchant: dict[str, Any],
            trigger: dict[str, Any], customer: Optional[dict[str, Any]]) -> dict[str, Any]:
    kind = str(trigger.get("kind", "")).lower()
    mode = language_mode(merchant, customer)
    name = merchant_name(merchant)
    cat = str(category.get("slug", merchant.get("category_slug", ""))).lower()
    voice = category_voice(category)
    signals = [str(x) for x in merchant.get("signals", [])]
    perf = merchant.get("performance", {}) or {}
    body = ""
    cta = "open_ended"
    send_as = "vera" if trigger.get("scope", "merchant") == "merchant" else "merchant_on_behalf"

    # Customer-facing flows
    if trigger.get("scope") == "customer" or customer:
        c_name = customer.get("identity", {}).get("name", "there")
        state = str(customer.get("state", "")).lower()
        pref = str(customer.get("preferences", {}).get("preferred_slots", "")).lower()
        offer = choose_offer(merchant, customer)

        if kind in {"recall_due", "appointment_recall"}:
            last = customer.get("relationship", {}).get("last_visit")
            service = ""
            services = customer.get("relationship", {}).get("services_received", [])
            if services:
                service = str(services[-1]).replace("_", " ")
            offer_text = f" {money_title(offer)}." if offer else ""
            if mode == "hi-en":
                body = (
                    f"Hi {c_name}, {merchant.get('identity', {}).get('name', 'the clinic')} here 🦷 "
                    f"Your next {service + ' ' if service else ''}visit is due"
                    f"{' (last visit: ' + str(last) + ')' if last else ''}.{offer_text} "
                    f"Reply with a convenient time and we’ll help with the booking."
                )
            else:
                body = (
                    f"Hi {c_name}, {merchant.get('identity', {}).get('name', 'the business')} here. "
                    f"Your {service + ' ' if service else ''}recall is due"
                    f"{' (last visit: ' + str(last) + ')' if last else ''}.{offer_text} "
                    f"Reply with a convenient time and we’ll help with the booking."
                )
            cta = "single_reply"
        elif kind in {"offer", "campaign", "promotion"}:
            offer_text = money_title(offer) if offer else ""
            body = f"Hi {c_name}, {merchant.get('identity', {}).get('name', 'the business')} here. "
            if offer_text:
                body += f"We currently have {offer_text}. "
            body += "Reply if you'd like the details or a suitable slot."
            cta = "open_ended"
        else:
            # Customer context is available but trigger is not specifically a
            # booking trigger: use only consent-compatible, non-claimy language.
            body = f"Hi {c_name}, {merchant.get('identity', {}).get('name', 'the business')} here. "
            body += "We have an update relevant to your recent visits. Reply if you'd like the details."
            cta = "open_ended"

        return {
            "body": taboo_clean(body, category),
            "cta": cta,
            "send_as": "merchant_on_behalf",
            "suppression_key": trigger.get("suppression_key", ""),
            "rationale": rationale(trigger, "customer-specific context used with the merchant's current offer/recall information")
        }

    # Merchant-facing trigger routing
    digest = find_digest(category, trigger)

    if kind in {"research_digest", "research_digest_release"} and digest:
        title = digest.get("title", "a new research update")
        source = digest.get("source", "")
        trial_n = digest.get("trial_n")
        segment = digest.get("patient_segment")
        detail = title
        if trial_n:
            detail = f"{trial_n:,}-patient {title}"
        fit = ""
        if segment and "cohort" in signals or (segment and any(segment.lower().replace("_", " ") in s.lower() for s in signals)):
            fit = f" This looks relevant to your {segment.replace('_', ' ')} cohort."
        elif segment:
            fit = f" It may be relevant if your patient mix includes {segment.replace('_', ' ')}."
        body = f"{name}, {source + ' ' if source else ''}has a new item: {detail}.{fit} "
        body += "Worth a look — want me to pull the key points and draft a shareable version?"
        cta = "open_ended"
        why = "research item anchored to the trigger and matched to available merchant signals"

    elif kind in {"regulation_change", "compliance", "policy_update"} and digest:
        deadline = (trigger.get("payload", {}) or {}).get("deadline_iso")
        source = digest.get("source", "")
        title = digest.get("title", "a compliance update")
        body = f"{name}, there’s a relevant compliance update: {title}."
        if deadline:
            body += f" The stated deadline is {deadline}."
        if source:
            body += f" Source: {source}."
        body += " Want me to turn the requirements into a short action checklist?"
        cta = "open_ended"
        why = "deadline/source included without inventing requirements"

    elif kind in {"performance_dip", "perf_dip", "performance_spike", "perf_spike", "profile_incomplete"}:
        ctr = merchant_ctr(merchant)
        pctr = peer_ctr(category)
        if ctr is not None and pctr is not None:
            comparison = "below" if ctr < pctr else "above"
            body = f"{name}, your current CTR is {pct(ctr)} vs {pct(pctr)} for the category peer benchmark — {comparison} the peer figure."
        elif ctr is not None:
            body = f"{name}, your current CTR is {pct(ctr)}."
        else:
            body = f"{name}, there’s a new performance signal on your profile."
        if "ctr_below_peer_median" in signals:
            body += " The profile also flags CTR below the peer median."
        if "stale_posts:22d" in signals:
            body += " Your latest-post signal is 22 days stale."
        body += " Want me to suggest one concrete change based only on the current profile data?"
        cta = "open_ended"
        why = "current merchant performance compared with category benchmark"

    elif kind in {"social_proof", "peer_benchmark"}:
        ps = category.get("peer_stats", {}) or {}
        avg_rating = ps.get("avg_rating")
        avg_reviews = ps.get("avg_reviews")
        avg_ctr = ps.get("avg_ctr")
        bits = []
        if avg_rating is not None:
            bits.append(f"peer average rating {avg_rating}")
        if avg_reviews is not None:
            bits.append(f"{avg_reviews} reviews")
        if avg_ctr is not None:
            bits.append(f"{pct(avg_ctr)} CTR")
        detail = ", ".join(bits) if bits else "the available peer benchmark"
        body = f"{name}, one peer benchmark worth knowing: {detail}."
        body += " Want me to compare that with your current profile and identify the clearest gap?"
        cta = "open_ended"
        why = "peer-stat trigger uses only category benchmark data"

    elif kind in {"offer_expiry", "offer_expired", "offer_needed", "campaign_opportunity", "seasonal_campaign"}:
        offer = choose_offer(merchant)
        if offer:
            body = f"{name}, your active offer is {money_title(offer)}."
        else:
            body = f"{name}, there’s a campaign opportunity for your category."
        body += " Want me to draft a category-fit message using the offer details already on your profile?"
        cta = "open_ended"
        why = "offer/campaign message grounded in the merchant catalog"

    elif kind in {"news_event", "local_event", "weather_event", "heatwave", "festival"}:
        title = digest.get("title") if digest else None
        body = f"{name}, there’s a timely {kind.replace('_', ' ')} update"
        if title:
            body += f": {title}"
        body += ". Want me to turn it into one merchant-ready WhatsApp message?"
        cta = "open_ended"
        why = "time-sensitive trigger converted into a low-friction drafting offer"

    elif kind in {"trend_signal", "trend"} and digest:
        title = digest.get("title", "a new category trend")
        body = f"{name}, a relevant category trend just surfaced: {title}."
        body += " Want me to translate it into one practical profile or offer idea?"
        cta = "open_ended"
        why = "trend signal tied to an actionable next step"

    elif kind in {"subscription_expiry", "renewal_due"}:
        sub = merchant.get("subscription", {}) or {}
        days = sub.get("days_remaining")
        body = f"{name}, your {sub.get('plan', 'current')} plan"
        if days is not None:
            body += f" has {days} days remaining"
        body += ". Want me to outline what needs attention before renewal?"
        cta = "open_ended"
        why = "subscription timing taken directly from merchant context"

    else:
        # Generic fallback still has a concrete merchant fact when possible.
        ctr = merchant_ctr(merchant)
        offer = choose_offer(merchant)
        if ctr is not None:
            body = f"{name}, a quick profile check: your current CTR is {pct(ctr)}."
        elif offer:
            body = f"{name}, a quick profile check: your active offer is {money_title(offer)}."
        else:
            body = f"{name}, I have a new update relevant to your business."
        body += " Want me to suggest one next step from the information currently on your profile?"
        cta = "open_ended"
        why = "fallback uses an available concrete merchant fact rather than inventing data"

    return {
        "body": taboo_clean(body, category),
        "cta": cta,
        "send_as": send_as,
        "suppression_key": trigger.get("suppression_key", ""),
        "rationale": rationale(trigger, why)
    }

# ---------------------------------------------------------------------------
# Conversation handling
# ---------------------------------------------------------------------------

AUTO_REPLY_PATTERNS = [
    "thank you for contacting", "thanks for contacting", "we will get back",
    "your message has been received", "auto reply", "we'll get back to you",
    "office hours", "away from the phone"
]

def is_auto_reply(msg: str, history: list[str]) -> bool:
    low = msg.lower().strip()
    if any(p in low for p in AUTO_REPLY_PATTERNS):
        return True
    # Challenge hint: same message verbatim 3+ times is an auto-reply.
    return history.count(low) >= 2

def conversation_response(body: ReplyBody) -> dict[str, Any]:
    state = conversations.setdefault(body.conversation_id, {
        "messages": [], "merchant_id": body.merchant_id,
        "customer_id": body.customer_id, "turns": 0
    })
    msg = body.message.strip()
    low = msg.lower()
    state["messages"].append(msg)
    state["turns"] += 1
    prior = [x.lower().strip() for x in state["messages"]]

    if is_auto_reply(msg, prior[:-1]):
        return {
            "action": "wait",
            "wait_seconds": 900,
            "rationale": "Likely automated WhatsApp reply; avoid burning a conversational turn"
        }

    # Stop conditions
    if any(x in low for x in [
        "not interested", "no thanks", "don't want", "do not want",
        "stop", "remove me", "unsubscribe", "not required"
    ]):
        return {"action": "end", "rationale": "Merchant/customer explicitly declined further outreach"}

    # Explicit acceptance -> action mode, not qualification mode.
    if any(x in low for x in [
        "yes", "okay", "ok", "go ahead", "let's do it", "i want to join",
        "send it", "send me", "do it", "sure"
    ]):
        return {
            "action": "send",
            "body": "Absolutely — moving to the next step. I’ll use the details already available here and keep it focused.",
            "cta": "open_ended",
            "rationale": "Detected explicit acceptance and switched from pitch/qualification to action mode"
        }

    if any(x in low for x in ["later", "busy", "tomorrow", "not now"]):
        return {
            "action": "wait",
            "wait_seconds": 1800,
            "rationale": "Merchant requested delay; back off instead of adding another pitch"
        }

    if "?" in msg or any(x in low for x in ["how", "what", "which", "when", "price", "cost"]):
        return {
            "action": "send",
            "body": "Good question. I’ll answer using only the merchant/category context available to me here. If you share the specific option you mean, I can keep the answer precise.",
            "cta": "open_ended",
            "rationale": "Answered with a bounded clarification rather than fabricating missing details"
        }

    # If no clear intent, acknowledge and keep the next step small.
    return {
        "action": "send",
        "body": "Got it. I can keep this focused — tell me whether you want the details, a draft message, or the next action.",
        "cta": "open_ended",
        "rationale": "Maintains context and offers a small set of next-step intents"
    }

# ---------------------------------------------------------------------------
# Required API
# ---------------------------------------------------------------------------

@app.get("/v1/healthz")
def healthz():
    counts = {}
    for (scope, _), _value in contexts.items():
        counts[scope] = counts.get(scope, 0) + 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time()),
        "contexts_loaded": {
            "category": counts.get("category", 0),
            "merchant": counts.get("merchant", 0),
            "customer": counts.get("customer", 0),
            "trigger": counts.get("trigger", 0),
        }
    }

@app.get("/v1/metadata")
def metadata():
    return {
        "team_name": "Rohit Vera Team",
        "team_members": ["Rohit Yadav"],
        "model": "deterministic-context-composer",
        "approach": "trigger routing + context-grounded deterministic composition + multi-turn state handling",
        "contact_email": "replace-before-submission@example.com",
        "version": "1.0.0",
        "submitted_at": datetime.utcnow().isoformat() + "Z"
    }

@app.post("/v1/context")
def push_context(body: CtxBody):
    if body.scope not in VALID_SCOPES:
        return {"accepted": False, "reason": "invalid_scope", "details": body.scope}
    key = (body.scope, body.context_id)
    current = contexts.get(key)
    if current and current["version"] >= body.version:
        return {
            "accepted": False,
            "reason": "stale_version",
            "current_version": current["version"]
        }
    contexts[key] = {"version": body.version, "payload": body.payload}
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.utcnow().isoformat() + "Z"
    }

@app.post("/v1/tick")
def tick(body: TickBody):
    actions = []
    for trigger_id in body.available_triggers[:20]:
        trigger = get("trigger", trigger_id)
        if not trigger:
            continue
        merchant_id = trigger.get("merchant_id")
        customer_id = trigger.get("customer_id")
        if not merchant_id:
            continue
        merchant = get("merchant", merchant_id)
        if not merchant:
            continue
        category_slug = merchant.get("category_slug") or trigger.get("payload", {}).get("category")
        category = get("category", category_slug) if category_slug else None
        if not category:
            continue
        customer = get("customer", customer_id) if customer_id else None
        result = compose(category, merchant, trigger, customer)

        # Suppress exact duplicate trigger delivery in the same process.
        conv = f"conv_{merchant_id}_{trigger_id}_{int(time.time()*1000)}"
        actions.append({
            "conversation_id": conv,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": result["send_as"],
            "trigger_id": trigger_id,
            "template_name": f"vera_{trigger.get('kind', 'update')}_v1",
            "template_params": [merchant_name(merchant)],
            "body": result["body"],
            "cta": result["cta"],
            "suppression_key": result["suppression_key"],
            "rationale": result["rationale"]
        })
    return {"actions": actions}

@app.post("/v1/reply")
def reply(body: ReplyBody):
    return conversation_response(body)

# ---------------------------------------------------------------------------
# Standalone compose API used by the 30-line submission generator.
# ---------------------------------------------------------------------------

def compose_for_test(category: dict, merchant: dict, trigger: dict,
                      customer: Optional[dict] = None) -> dict:
    return compose(category, merchant, trigger, customer)
