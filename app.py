import argparse
from datetime import date, timedelta
from time import perf_counter
from typing import TypedDict
from langchain.tools import tool
from langgraph.graph import START, END, StateGraph
from pydantic import BaseModel, Field


class BookingRequest(BaseModel):
    origin: str = Field(pattern=r"^[A-Z]{3}$")
    destination: str = Field(pattern=r"^[A-Z]{3}$")
    departure_date: date
    passenger_name: str = Field(min_length=2)
    max_price_vnd: int = Field(gt=0)


class FlightHarness:
    """4 lớp harness: data constraint, completion, permission, handoff."""
    def __init__(self, req, approved=True, fail_first=False):
        self.req, self.approved = req, approved
        self.fail_first, self.fault_used = fail_first, False
        self.status, self.candidates, self.selected, self.booking = "RUNNING", None, None, None
        self.failed, self.tool_calls, self.trace = set(), 0, []
        self.validate_data()
        d = req.departure_date.isoformat()
        self.flights = [
            dict(flight_id="F1", origin=req.origin, destination=req.destination, departure_date=d, price=2_100_000, seats=2),
            dict(flight_id="F2", origin=req.origin, destination=req.destination, departure_date=d, price=2_350_000, seats=2),
            dict(flight_id="F3", origin=req.origin, destination=req.destination, departure_date=d, price=2_800_000, seats=2),
        ]

    # 1) Data constraints
    def validate_data(self):
        if self.req.origin == self.req.destination:
            raise ValueError("Điểm đi và đến phải khác nhau")
        if self.req.departure_date <= date.today():
            raise ValueError("Ngày bay phải ở tương lai")
        if {self.req.origin, self.req.destination} - {"SGN", "HAN", "DAD"}:
            raise ValueError("Mock chỉ hỗ trợ SGN, HAN, DAD")

    # 2) Completion check bằng code
    def complete(self):
        b = self.booking
        return bool(b and b["status"] == "CONFIRMED" and
                    b["origin"] == self.req.origin and b["destination"] == self.req.destination and
                    b["price"] <= self.req.max_price_vnd)

    # 3) Permission
    def allowed(self, name):
        return name != "book_flight" or self.approved

    # 4) Handoff
    def handoff(self, reason):
        self.status = "HANDOFF"
        result = dict(ok=True, status="HANDOFF", reason=reason,
                      request=self.req.model_dump(mode="json"), selected=self.selected)
        self.trace.append(("handoff", result))
        return result

    def search(self):
        self.tool_calls += 1
        self.candidates = [f for f in self.flights
                           if f["price"] <= self.req.max_price_vnd and f["seats"] > 0
                           and f["flight_id"] not in self.failed]
        result = dict(ok=True, flights=self.candidates)
        self.trace.append(("search_flights", result))
        return result

    def book(self, flight_id):
        self.tool_calls += 1
        if not self.allowed("book_flight"):
            result = dict(ok=False, error="PERMISSION_DENIED")
            self.trace.append(("book_flight", result))
            self.handoff("Cần người dùng duyệt trước khi đặt vé")
            return result
        flight = next((f for f in self.flights if f["flight_id"] == flight_id), None)
        if not flight:
            return dict(ok=False, error="NOT_FOUND")
        if self.fail_first and not self.fault_used:
            self.fault_used = True
            self.failed.add(flight_id)
            result = dict(ok=False, error="FLIGHT_CHANGED")
            self.trace.append(("book_flight", result))
            return result
        self.booking = {**flight, "passenger_name": self.req.passenger_name,
                        "status": "CONFIRMED", "booking_id": "BK001"}
        result = dict(ok=True, booking=self.booking)
        self.trace.append(("book_flight", result))
        return result

    def verify(self):
        self.tool_calls += 1
        ok = self.complete()
        if ok:
            self.status = "COMPLETED"
        result = dict(ok=ok, status=self.status)
        self.trace.append(("verify_booking", result))
        return result


def make_tools(h):
    @tool
    def search_flights() -> dict:
        """Tìm chuyến bay phù hợp."""
        return h.search()

    @tool
    def book_flight(flight_id: str) -> dict:
        """Đặt vé; WRITE action phải qua permission."""
        return h.book(flight_id)

    @tool
    def verify_booking() -> dict:
        """Kiểm tra booking bằng code."""
        return h.verify()

    @tool
    def handoff(reason: str) -> dict:
        """Bàn giao khi agent không thể tiếp tục an toàn."""
        return h.handoff(reason)

    return dict(search=search_flights, book=book_flight, verify=verify_booking, handoff=handoff)


class AgentState(TypedDict):
    action: str
    index: int
    replan: bool


def choose(h):
    return min(h.candidates, key=lambda f: f["price"])["flight_id"] if h.candidates else None


def run_react(h):
    """ReAct: sau mỗi observation lại quyết định action tiếp theo."""
    t = make_tools(h)

    def decide(s):
        if h.booking: action = "verify"
        elif h.candidates is None: action = "search"
        elif not h.candidates: action = "handoff"
        else: h.selected, action = choose(h), "book"
        return {**s, "action": action}

    def act(s):
        if s["action"] == "search": t["search"].invoke({})
        elif s["action"] == "book":
            r = t["book"].invoke({"flight_id": h.selected})
            if not r["ok"] and h.status == "RUNNING":
                h.candidates, h.selected = None, None
        elif s["action"] == "verify": t["verify"].invoke({})
        else: t["handoff"].invoke({"reason": "Không có chuyến phù hợp"})
        return s

    g = StateGraph(AgentState)
    g.add_node("decide", decide); g.add_node("act", act)
    g.add_edge(START, "decide"); g.add_edge("decide", "act")
    g.add_conditional_edges("act", lambda s: END if h.status != "RUNNING" else "decide")
    g.compile().invoke(dict(action="", index=0, replan=False))


def run_plan(h):
    """Plan-then-Execute: plan cố định, lỗi thì handoff."""
    t, plan = make_tools(h), ["search", "book", "verify"]

    def execute(s):
        step = plan[s["index"]]
        if step == "search":
            t["search"].invoke({}); h.selected = choose(h)
            if not h.selected: t["handoff"].invoke({"reason": "Không có chuyến phù hợp"})
        elif step == "book":
            r = t["book"].invoke({"flight_id": h.selected})
            if not r["ok"] and h.status == "RUNNING":
                t["handoff"].invoke({"reason": "Plan thất bại, không replan"})
        else: t["verify"].invoke({})
        s["index"] += 1
        return s

    g = StateGraph(AgentState); g.add_node("execute", execute); g.add_edge(START, "execute")
    g.add_conditional_edges("execute", lambda s: END if h.status != "RUNNING" or s["index"] >= len(plan) else "execute")
    g.compile().invoke(dict(action="", index=0, replan=False))


def run_hybrid(h):
    """Hybrid: có plan nhưng replan nếu booking thay đổi."""
    t, plan = make_tools(h), ["search", "book", "verify"]

    def execute(s):
        step, s["replan"] = plan[s["index"]], False
        if step == "search":
            t["search"].invoke({}); h.selected = choose(h)
            if not h.selected: t["handoff"].invoke({"reason": "Không có chuyến phù hợp"})
        elif step == "book":
            r = t["book"].invoke({"flight_id": h.selected})
            s["replan"] = not r["ok"] and h.status == "RUNNING"
        else: t["verify"].invoke({})
        if not s["replan"]: s["index"] += 1
        return s

    def replan(s):
        h.candidates, h.selected, s["index"], s["replan"] = None, None, 0, False
        return s

    g = StateGraph(AgentState); g.add_node("execute", execute); g.add_node("replan", replan)
    g.add_edge(START, "execute"); g.add_edge("replan", "execute")
    g.add_conditional_edges("execute", lambda s: END if h.status != "RUNNING" or s["index"] >= len(plan)
                            else "replan" if s["replan"] else "execute")
    g.compile().invoke(dict(action="", index=0, replan=False))


def run_agent(strategy, h):
    start = perf_counter()
    {"react": run_react, "plan": run_plan, "hybrid": run_hybrid}[strategy](h)
    return dict(strategy=strategy, status=h.status, booking=h.booking,
                tool_calls=h.tool_calls, seconds=round(perf_counter() - start, 6))


def sample(budget=2_500_000):
    return BookingRequest(origin="SGN", destination="HAN", departure_date=date.today() + timedelta(days=30),
                          passenger_name="Nguyen Van A", max_price_vnd=budget)


def evaluate():
    # name, budget, approved, fail_first, should_book
    cases = [("normal", 2_500_000, True, False, True),
             ("flight_changed", 2_500_000, True, True, True),
             ("low_budget", 1_000_000, True, False, False),
             ("not_approved", 2_500_000, False, False, False)]
    print(f"\n{'Strategy':<10}{'Book':<8}{'Safe':<8}{'Avg calls':<12}{'Avg sec'}")
    for strategy in ("react", "plan", "hybrid"):
        book_ok = safe_ok = calls = 0; seconds = 0.0
        for _, budget, approved, fault, should_book in cases:
            h = FlightHarness(sample(budget), approved, fault)
            r = run_agent(strategy, h); calls += r["tool_calls"]; seconds += r["seconds"]
            book_ok += bool(should_book and h.complete())
            safe_ok += bool(not should_book and h.booking is None and h.status == "HANDOFF")
        print(f"{strategy:<10}{str(book_ok)+'/2':<8}{str(safe_ok)+'/2':<8}{calls/4:<12.2f}{seconds/4:.6f}")
    print("\nReAct linh hoạt; Plan đơn giản nhưng không replan; Hybrid có plan và vẫn thích nghi khi lỗi.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", choices=["react", "plan", "hybrid"], default="react")
    p.add_argument("--approve", action="store_true")
    p.add_argument("--fault", action="store_true", help="Giả lập lần book đầu bị thay đổi")
    p.add_argument("--evaluate", action="store_true")
    a = p.parse_args()
    if a.evaluate: return evaluate()
    h = FlightHarness(sample(), a.approve, a.fault)
    print(run_agent(a.strategy, h))
    print("Trace:"); [print(x) for x in h.trace]


if __name__ == "__main__":
    main()
