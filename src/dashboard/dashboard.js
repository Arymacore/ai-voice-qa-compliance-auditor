"use strict";

/*
=========================================================
MIDNIGHT VIOLET
AI Voice QA & Compliance Auditor

Frontend responsibilities:
1. Fetch dashboard analytics
2. Display compliance distribution
3. Render risk indicators
4. List and filter analyzed calls
5. Display individual call results
6. Highlight transcript evidence
7. Upload and delete calls

Security:
All untrusted content is rendered as plain text.
Dynamic elements are created using safe DOM methods.
Uploaded transcripts are never interpreted as markup.
=========================================================
*/

(function () {

    // =====================================================
    // APPLICATION STATE
    // =====================================================

    const state = {
        status: "",
        reviewOnly: false,
        selected: null
    };

    const PRIORITY = {
        tone: 1,
        disclosure: 2,
        violation: 3
    };

    const KIND_CLASS = {
        violation: "hl-violation",
        disclosure: "hl-disclosure",
        tone: "hl-tone"
    };

    const KIND_TITLE = {
        violation: "Violation",
        disclosure: "Required disclosure given",
        tone: "Tone concern"
    };


    // =====================================================
    // DOM HELPERS
    // =====================================================

    function el(tag, props, children) {

        const node = document.createElement(tag);

        if (props) {

            for (const [key, value] of Object.entries(props)) {

                if (key === "class") {
                    node.className = value;
                }

                else if (key === "text") {
                    node.textContent = String(value);
                }

                else {
                    node.setAttribute(key, value);
                }
            }
        }

        for (const child of children || []) {
            node.append(child);
        }

        return node;
    }


    function badge(text, kind) {

        return el("span", {
            class: "badge " + kind,
            text: text
        });
    }


    function statusKind(status) {

        return {
            PASS: "ok",
            REVIEW: "warn",
            FAIL: "bad"
        }[status] || "neutral";
    }


    function toneKind(flag) {

        return {
            OK: "ok",
            REVIEW: "warn"
        }[flag] || "neutral";
    }


    function when(iso) {

        if (!iso) return "—";

        const date = new Date(iso);

        return Number.isNaN(date.getTime())
            ? "—"
            : date.toLocaleString();
    }


    function showMessage(message, isError = false) {

        const box = document.getElementById("message");

        box.textContent = message || "";

        box.className = isError ? "error" : "";
    }


    // =====================================================
    // API COMMUNICATION
    // =====================================================

    async function api(path, options) {

        const response = await fetch(path, options);

        if (response.status === 401) {
            window.location.href = "/login";

            throw new Error(
                "Your session expired. Redirecting to sign in."
            );
        }

        if (!response.ok) {

            let detail = response.statusText;

            try {

                const body = await response.json();

                detail = typeof body.detail === "string"
                    ? body.detail
                    : JSON.stringify(body.detail);

            } catch (ignored) {
                // Keep HTTP status text.
            }

            throw new Error(
                detail || "Request failed (" + response.status + ")"
            );
        }

        if (response.status === 204) {
            return null;
        }

        return response.json();
    }


    // =====================================================
    // ANALYTICS SUMMARY CARDS
    // =====================================================

    function renderSummary(summary) {

        const metrics = [

            {
                label: "Total Conversations",
                value: summary.total,
                icon: "◈",
                footer: "All analyzed calls"
            },

            {
                label: "Needs Attention",
                value: summary.needs_review,
                icon: "⚑",
                footer: "Conversations requiring review"
            },

            {
                label: "Compliance Failures",
                value: summary.by_status.FAIL,
                icon: "✕",
                footer: "Calls with compliance violations"
            },

            {
                label: "Pending Review",
                value: summary.by_status.REVIEW,
                icon: "◎",
                footer: "Calls marked for review"
            },

            {
                label: "Compliance Passed",
                value: summary.by_status.PASS,
                icon: "✓",
                footer: "Calls meeting compliance checks"
            },

            {
                label: "Tone Concerns",
                value: summary.tone_review,
                icon: "◇",
                footer: "Calls flagged for agent tone"
            }
        ];

        const container = document.getElementById("summary");

        const cards = metrics.map(metric => {

            const top = el("div", {
                class: "metric-top"
            }, [

                el("span", {
                    class: "metric-label",
                    text: metric.label
                }),

                el("span", {
                    class: "metric-icon",
                    text: metric.icon
                })

            ]);

            return el("div", {
                class: "metric-card"
            }, [

                top,

                el("div", {
                    class: "metric-value",
                    text: metric.value ?? 0
                }),

                el("div", {
                    class: "metric-footer",
                    text: metric.footer
                })

            ]);
        });

        container.replaceChildren(...cards);
    }


    // =====================================================
    // COMPLIANCE DONUT CHART
    // =====================================================

    function renderDistribution(summary) {

        const total = Number(summary.total) || 0;

        const passed = Number(summary.by_status.PASS) || 0;
        const failed = Number(summary.by_status.FAIL) || 0;
        const review = Number(summary.by_status.REVIEW) || 0;

        const donut = document.getElementById(
            "compliance-donut"
        );

        document.getElementById(
            "donut-total"
        ).textContent = total;

        const legend = document.getElementById(
            "distribution-legend"
        );

        const categories = [

            {
                label: "Passed",
                value: passed,
                color: "#34d399"
            },

            {
                label: "Failed",
                value: failed,
                color: "#fb7185"
            },

            {
                label: "Review",
                value: review,
                color: "#fbbf24"
            }
        ];

        // Calculate the chart from actual database counts.
        const passEnd = total ? passed / total * 100 : 0;

        const failEnd = total
            ? (passed + failed) / total * 100
            : 0;

        if (total === 0) {

            donut.style.background =
                "conic-gradient(#241c3d 0% 100%)";

        } else {

            donut.style.background = `conic-gradient(
                #34d399 0% ${passEnd}%,
                #fb7185 ${passEnd}% ${failEnd}%,
                #fbbf24 ${failEnd}% 100%
            )`;
        }

        const rows = categories.map(category => {

            const dot = el("span", {
                class: "legend-dot"
            });

            dot.style.backgroundColor = category.color;

            const name = el("span", {
                class: "legend-name"
            }, [

                dot,

                document.createTextNode(category.label)

            ]);

            return el("div", {
                class: "legend-row"
            }, [

                name,

                el("strong", {
                    class: "legend-value",
                    text: category.value
                })

            ]);
        });

        legend.replaceChildren(...rows);
    }


    // =====================================================
    // RISK OVERVIEW
    // =====================================================

    function renderRiskInsights(summary) {

        const total = Number(summary.total) || 0;

        const risks = [

            {
                label: "Compliance Failures",
                count: Number(summary.by_status.FAIL) || 0,
                color: "#fb7185",
                description: "Calls failing compliance checks"
            },

            {
                label: "Requires Review",
                count: Number(summary.needs_review) || 0,
                color: "#a78bfa",
                description: "Calls requiring human attention"
            },

            {
                label: "Tone Concerns",
                count: Number(summary.tone_review) || 0,
                color: "#fbbf24",
                description: "Calls with flagged agent tone"
            }

        ];

        const container = document.getElementById(
            "risk-insights"
        );

        const items = risks.map(risk => {

            const percentage = total
                ? Math.min(100, risk.count / total * 100)
                : 0;

            const fill = el("div", {
                class: "risk-fill"
            });

            fill.style.width = percentage + "%";
            fill.style.backgroundColor = risk.color;

            const track = el("div", {
                class: "risk-track"
            }, [fill]);

            const heading = el("div", {
                class: "risk-heading"
            }, [

                el("span", {
                    text: risk.label
                }),

                el("strong", {
                    text: percentage.toFixed(1) + "%"
                })

            ]);

            return el("div", {
                class: "risk-item"
            }, [

                heading,

                track,

                el("div", {
                    class: "risk-description",
                    text: risk.count + " calls · " + risk.description
                })

            ]);
        });

        container.replaceChildren(...items);
    }


    // =====================================================
    // CALL TABLE
    // =====================================================

    function renderList(rows) {

        const body = document.querySelector(
            "#calls tbody"
        );

        if (!rows.length) {

            body.replaceChildren(

                el("tr", null, [

                    el("td", {
                        colspan: "5",
                        class: "empty",
                        text: "No calls match these filters."
                    })

                ])

            );

            return;
        }

        const tableRows = rows.map(row => {

            const open = el("button", {
                type: "button",
                class: "call-link",
                text: row.call_id
            });

            open.addEventListener("click", () => {
                openCall(row.call_id);
            });

            const tr = el("tr",
                row.call_id === state.selected
                    ? { class: "selected" }
                    : null
            );

            if (row.error) {

                tr.append(

                    el("td", null, [open]),

                    el("td", {
                        colspan: "4",
                        text: "Unreadable: " + row.error
                    })

                );

                return tr;
            }

            const score = value =>
                value === null || value === undefined
                    ? "n/a"
                    : String(value);

            tr.append(

                el("td", null, [open]),

                el("td", null, [

                    badge(
                        row.compliance_status,
                        statusKind(row.compliance_status)
                    ),

                    el("span", {
                        class: "small",
                        text: score(row.compliance_score) + "/100 | combined " + score(row.combined_score)
                    })

                ]),

                el("td", null, [

                    badge(
                        row.tone_flag,
                        toneKind(row.tone_flag)
                    ),

                    el("span", {
                        class: "small",
                        text: score(row.tone_score) +
                            (row.tone_score === null ? "" : "/100")
                    })

                ]),

                el("td", {
                    text: (row.review_reasons || []).length
                        ? row.review_reasons.join(", ")
                        : "—"
                }),

                el("td", {
                    text: when(row.analyzed_at)
                })

            );

            return tr;
        });

        body.replaceChildren(...tableRows);
    }


    // =====================================================
    // EVIDENCE HIGHLIGHTING
    // =====================================================

    function straighten(text) {

        return String(text)
            .replace(/[\u2018\u2019]/g, "'")
            .replace(/[\u201C\u201D]/g, '"');
    }


    function escapeRegExp(text) {

        return text.replace(
            /[.*+?^${}()|[\]\\]/g,
            "\\$&"
        );
    }


    function splitEvidence(evidence) {

        const whole = String(evidence).trim();

        const parts = whole
            .split(/(?<=[.!?])\s+/)
            .map(s => s.trim())
            .filter(s => s.length >= 6);

        return parts.length
            ? parts
            : whole ? [whole] : [];
    }


    function agentLineIndexes(lines) {

        const labelled = [];

        lines.forEach((line, index) => {

            if (/^\s*agent:/i.test(line)) {
                labelled.push(index);
            }

        });

        return labelled.length
            ? labelled
            : lines.map((_, index) => index);
    }


    function findRanges(lines, items) {

        const candidates = agentLineIndexes(lines);

        const ranges = lines.map(() => []);

        for (const item of items) {

            for (const fragment of splitEvidence(item.evidence)) {

                const needle = new RegExp(
                    escapeRegExp(straighten(fragment)),
                    "i"
                );

                for (const index of candidates) {

                    const match = needle.exec(
                        straighten(lines[index])
                    );

                    if (match) {

                        ranges[index].push({

                            start: match.index,

                            end: match.index + match[0].length,

                            kind: item.kind,

                            label: item.label

                        });

                        break;
                    }
                }
            }
        }

        return ranges;
    }


    function lineSegments(text, ranges) {

        const cuts = new Set([0, text.length]);

        ranges.forEach(range => {

            cuts.add(range.start);
            cuts.add(range.end);

        });

        const points = Array.from(cuts)
            .sort((a, b) => a - b);

        const segments = [];

        for (let i = 0; i < points.length - 1; i++) {

            const start = points[i];
            const end = points[i + 1];

            if (start === end) continue;

            const covering = ranges.filter(range =>
                range.start <= start && range.end >= end
            );

            let kind = null;

            for (const range of covering) {

                if (
                    kind === null ||
                    PRIORITY[range.kind] > PRIORITY[kind]
                ) {
                    kind = range.kind;
                }
            }

            const labels = kind
                ? Array.from(new Set(
                    covering
                        .filter(range => range.kind === kind)
                        .map(range => range.label)
                ))
                : [];

            segments.push({

                text: text.slice(start, end),

                kind: kind,

                label: labels.join(", ") || null

            });
        }

        return segments;
    }


    function collectHighlights(result) {

        const items = [];

        for (const rule of result.compliance.rules) {

            if (!rule.evidence) continue;

            if (
                rule.type === "prohibited" &&
                !rule.passed
            ) {

                items.push({

                    evidence: rule.evidence,
                    kind: "violation",
                    label: rule.rule_id

                });
            }

            if (
                rule.type === "required" &&
                rule.passed
            ) {

                items.push({

                    evidence: rule.evidence,
                    kind: "disclosure",
                    label: rule.rule_id

                });
            }
        }

        for (const rating of result.tone.ratings) {

            if (
                rating.score !== null &&
                rating.score <= 2 &&
                rating.evidence
            ) {

                items.push({

                    evidence: rating.evidence,
                    kind: "tone",
                    label: rating.dimension

                });
            }
        }

        return items;
    }


    function renderTranscript(transcript, items) {

        const lines = String(transcript).split("\n");

        const ranges = findRanges(lines, items);

        const renderedLines = lines.map((line, index) => {

            const segments = lineSegments(
                line,
                ranges[index]
            );

            const children = segments.map(segment => {

                if (!segment.kind) {

                    return document.createTextNode(
                        segment.text
                    );
                }

                return el("span", {

                    class: KIND_CLASS[segment.kind],

                    title: KIND_TITLE[segment.kind] +
                        " (" + segment.label + ")",

                    text: segment.text

                });
            });

            return el("div", {
                class: "line"
            }, children);
        });

        return el("div", {
            class: "transcript"
        }, renderedLines);
    }


    // =====================================================
    // DETAIL TABLE HELPERS
    // =====================================================

    function table(headers, rows) {

        return el("table", null, [

            el("thead", null, [

                el("tr", null,

                    headers.map(header =>
                        el("th", {
                            scope: "col",
                            text: header
                        })
                    )

                )

            ]),

            el("tbody", null, rows)

        ]);
    }


    function ruleRow(rule) {

        const required = rule.type === "required";

        const label = required
            ? (rule.passed ? "Met" : "Missing")
            : (rule.passed ? "Clear" : "Violation");

        return el("tr", null, [

            el("td", {
                text: rule.rule_id + " · " + rule.name
            }),

            el("td", {
                text: rule.severity
            }),

            el("td", null, [

                badge(
                    label,
                    rule.passed ? "ok" : "bad"
                )

            ]),

            el("td", {
                text: rule.source === "llm"
                    ? "AI judgment"
                    : "Pattern match"
            }),

            el("td", {
                text: rule.evidence || "—"
            })

        ]);
    }


    function fill(score) {

        const node = el("span", {
            class: "fill"
        });

        node.style.width = (score / 5) * 100 + "%";

        return node;
    }


    function toneRow(rating) {

        const unrated = rating.score === null;

        const meter = unrated

            ? el("span", {
                class: "small",
                text: "Unrated"
            })

            : el("span", null, [

                el("span", {
                    class: "bar"
                }, [
                    fill(rating.score)
                ]),

                el("span", {
                    class: "small",
                    text: rating.score + "/5"
                })

            ]);

        const note = unrated

            ? "Could not be verified: " +
                (rating.reason || "No reason provided")

            : rating.evidence ||
                "No supporting agent quote available";

        return el("tr", null, [

            el("td", {
                text: rating.dimension
            }),

            el("td", null, [meter]),

            el("td", {
                text: note
            })

        ]);
    }


    // =====================================================
    // CALL DETAIL VIEW
    // =====================================================

    function renderDetail(result) {

        const box = document.getElementById("detail");

        if (result.error) {

            box.replaceChildren(

                el("h2", {
                    text: result.call_id
                }),

                el("p", {
                    text: "Unreadable: " + result.error
                })

            );

            return;
        }

        const parts = [];

        const heading = el("div", {
            class: "detail-heading"
        }, [

            el("h2", {
                text: result.call_id
            }),

            el("div", {
                class: "badges"
            }, [

                badge(
                    "Compliance " + result.compliance.status +
                    " · " + result.compliance.score + "/100",

                    statusKind(result.compliance.status)
                ),

                badge(
                    "Tone " + result.tone.flag +
                    (
                        result.tone.score === null
                            ? ""
                            : " · " + result.tone.score + "/100"
                    ),

                    toneKind(result.tone.flag)
                ),

                badge(
                    "Combined " + (
                        result.combined_score === undefined || result.combined_score === null
                            ? "n/a"
                            : result.combined_score + "/100"
                    ),
                    "neutral"
                )

            ])

        ]);

        parts.push(heading);

        const reviewText = result.needs_review

            ? "Needs review: " +
                result.review_reasons.join(", ")

            : "No review needed";

        parts.push(

            el("p", {

                class: "meta",

                text: reviewText +
                    " · " + result.source_file +
                    " · Analyzed " + when(result.analyzed_at) +
                    " · Engine: " + result.compliance.engine

            })

        );

        if (result.compliance.llm_error) {

            parts.push(

                el("p", {
                    class: "meta",
                    text: "Note: " + result.compliance.llm_error
                })

            );
        }

        // Compliance section

        parts.push(

            el("h3", {
                text: "Compliance Rules"
            })

        );

        parts.push(

            table(

                [
                    "Rule",
                    "Severity",
                    "Result",
                    "Decided By",
                    "Evidence"
                ],

                result.compliance.rules.map(ruleRow)

            )

        );

        // Tone section

        parts.push(

            el("h3", {
                text: "Agent Tone Analysis"
            })

        );

        if (!result.tone.available) {

            parts.push(

                el("p", {

                    class: "meta",

                    text: "Tone scoring was unavailable" +
                        (
                            result.tone.error
                                ? ": " + result.tone.error
                                : "."
                        )

                })

            );

        } else {

            parts.push(

                table(

                    [
                        "Quality Dimension",
                        "Rating",
                        "Evidence"
                    ],

                    result.tone.ratings.map(toneRow)

                )

            );
        }

        // Transcript section

        parts.push(

            el("h3", {
                text: "Transcript Evidence"
            })

        );

        const legend = el("div", {
            class: "legend"
        });

        for (const kind of Object.keys(KIND_CLASS)) {

            legend.append(

                el("span", null, [

                    el("span", {

                        class: KIND_CLASS[kind],

                        text: KIND_TITLE[kind]

                    })

                ])

            );
        }

        parts.push(legend);

        if (result.transcript) {

            parts.push(

                renderTranscript(
                    result.transcript,
                    collectHighlights(result)
                )

            );

        } else {

            parts.push(

                el("p", {

                    class: "meta",

                    text: "Transcript was not stored for this call."

                })

            );
        }

        // Delete button

        const deleteButton = el("button", {

            type: "button",

            class: "danger",

            text: "Delete This Call"

        });

        deleteButton.addEventListener("click", () => {

            removeCall(result.call_id);

        });

        parts.push(

            el("p", null, [deleteButton])

        );

        box.replaceChildren(...parts);
    }


    // =====================================================
    // DATA LOADING
    // =====================================================

    async function loadSummary() {

        const summary = await api("/api/summary");

        renderSummary(summary);

        renderDistribution(summary);

        renderRiskInsights(summary);
    }


    async function loadList() {

        const params = new URLSearchParams({
            limit: "200"
        });

        if (state.status) {

            params.set("status", state.status);
        }

        if (state.reviewOnly) {

            params.set("needs_review", "true");
        }

        const rows = await api(
            "/api/calls?" + params.toString()
        );

        renderList(rows);
    }


    async function refresh() {

        try {

            showMessage("");

            await Promise.all([

                loadSummary(),

                loadList()

            ]);

        } catch (error) {

            showMessage(error.message, true);
        }
    }


    // =====================================================
    // OPEN A CALL
    // =====================================================

    async function openCall(callId) {

        try {

            showMessage("");

            state.selected = callId;

            const result = await api(
                "/api/calls/" + encodeURIComponent(callId)
            );

            renderDetail(result);

            await loadList();

            document.getElementById("detail")
                .scrollIntoView({
                    behavior: "smooth",
                    block: "start"
                });

        } catch (error) {

            showMessage(error.message, true);
        }
    }


    // =====================================================
    // DELETE A CALL
    // =====================================================

    // =====================================================
// DELETE CONFIRMATION MODAL
// =====================================================

function confirmDelete(callId) {

    return new Promise(resolve => {

        const modal = document.getElementById("delete-modal");

        const callLabel = document.getElementById(
            "delete-modal-call-id"
        );

        const cancelButton = document.getElementById(
            "delete-modal-cancel"
        );

        const confirmButton = document.getElementById(
            "delete-modal-confirm"
        );

        const previousFocus = document.activeElement;

        callLabel.textContent = callId;

        modal.hidden = false;

        cancelButton.focus();

        function cleanup(confirmed) {

            modal.hidden = true;

            cancelButton.removeEventListener(
                "click",
                onCancel
            );

            confirmButton.removeEventListener(
                "click",
                onConfirm
            );

            modal.removeEventListener(
                "click",
                onBackdrop
            );

            document.removeEventListener(
                "keydown",
                onKeyDown
            );

            if (
                previousFocus &&
                previousFocus.isConnected &&
                typeof previousFocus.focus === "function"
            ) {
                previousFocus.focus();
            }

            resolve(confirmed);
        }

        function onCancel() {
            cleanup(false);
        }

        function onConfirm() {
            cleanup(true);
        }

        function onBackdrop(event) {

            if (event.target === modal) {
                cleanup(false);
            }
        }

        function onKeyDown(event) {

            if (event.key === "Escape") {
                event.preventDefault();
                cleanup(false);
            }

            if (event.key === "Tab") {

                const focusable = [
                    cancelButton,
                    confirmButton
                ];

                const currentIndex = focusable.indexOf(
                    document.activeElement
                );

                if (event.shiftKey && currentIndex === 0) {
                    event.preventDefault();
                    confirmButton.focus();
                }

                else if (
                    !event.shiftKey &&
                    currentIndex === focusable.length - 1
                ) {
                    event.preventDefault();
                    cancelButton.focus();
                }
            }
        }

        cancelButton.addEventListener(
            "click",
            onCancel
        );

        confirmButton.addEventListener(
            "click",
            onConfirm
        );

        modal.addEventListener(
            "click",
            onBackdrop
        );

        document.addEventListener(
            "keydown",
            onKeyDown
        );
    });
}


// =====================================================
// DELETE A CALL
// =====================================================

async function removeCall(callId) {

    const confirmed = await confirmDelete(callId);

    if (!confirmed) return;

    try {

        await api(
            "/api/calls/" + encodeURIComponent(callId),
            {
                method: "DELETE"
            }
        );

        state.selected = null;

        document.getElementById("detail")
            .replaceChildren(

                el("div", {
                    class: "empty-detail"
                }, [

                    el("h2", {
                        text: "Conversation Inspector"
                    }),

                    el("p", {
                        text: "Select another call to inspect."
                    })

                ])

            );

        showMessage("Deleted " + callId + ".");

        await Promise.all([
            loadSummary(),
            loadList()
        ]);

    } catch (error) {

        showMessage(error.message, true);
    }
}


    // =====================================================
    // UPLOAD A CALL
    // =====================================================

    async function uploadCall(file) {

        const form = new FormData();

        form.append("file", file);

        try {

            showMessage(
                "Analyzing " + file.name + "…"
            );

            const result = await api(
                "/api/calls/analyze",
                {
                    method: "POST",
                    body: form
                }
            );

            state.selected = result.call_id;

            renderDetail(result);

            await Promise.all([

                loadSummary(),

                loadList()

            ]);

            showMessage(
                "Successfully analyzed " + file.name + "."
            );

            document.getElementById("detail")
                .scrollIntoView({
                    behavior: "smooth"
                });

        } catch (error) {

            showMessage(error.message, true);
        }
    }


    // =====================================================
    // INITIALIZATION
    // =====================================================

    function initUserMenu() {
        const button = document.getElementById("user-menu-button");
        const panel = document.getElementById("user-menu-panel");
        if (!button || !panel) return;

        function setOpen(open) {
            panel.hidden = !open;
            button.setAttribute("aria-expanded", String(open));
        }

        button.addEventListener("click", event => {
            event.stopPropagation();
            setOpen(panel.hidden);
        });

        document.addEventListener("click", event => {
            if (!panel.hidden && !panel.contains(event.target)) {
                setOpen(false);
            }
        });

        document.addEventListener("keydown", event => {
            if (event.key === "Escape" && !panel.hidden) {
                setOpen(false);
                button.focus();
            }
        });

        api("/api/me").then(me => {
            const initials = String(me.username).slice(0, 2).toUpperCase();
            document.getElementById("user-menu-name").textContent = me.username;
            document.getElementById("user-menu-avatar").textContent = initials;
            button.textContent = initials;
        }).catch(() => {
            // Keep the default "QA" label if the lookup fails.
        });
    }


    function initNavigation() {
    const links = document.querySelectorAll(".sidebar-nav .nav-item");

    function updateActiveLink(hash) {
        const target = hash || "#overview";

        links.forEach(link => {
            const isActive = link.getAttribute("href") === target;

            link.classList.toggle("active", isActive);
            if (isActive) {
                link.setAttribute("aria-current", "page");
            } else {
                link.removeAttribute("aria-current");
            }
        });
    }

    links.forEach(link => {
        link.addEventListener("click", () => {
            updateActiveLink(link.getAttribute("href"));
        });
    });

    window.addEventListener("hashchange", () => {
        updateActiveLink(window.location.hash);
    });

    updateActiveLink(window.location.hash);
}

    function initAnalyzeModal() {
    const modal = document.getElementById("analyze-modal");
    const openButton = document.getElementById("analyze-call-open");
    const cancelButton = document.getElementById("analyze-modal-cancel");
    const audioButton = document.getElementById("choose-audio");
    const transcriptButton = document.getElementById("choose-transcript");
    const audioInput = document.getElementById("audio-upload-input");
    const transcriptInput = document.getElementById("transcript-upload-input");
    const selectedBox = document.getElementById("selected-upload");
    const selectedName = document.getElementById("selected-upload-name");
    const status = document.getElementById("upload-modal-status");
    const submitButton = document.getElementById("analyze-modal-submit");

    let selectedFile = null;
    let processing = false;

    function resetModal() {
        selectedFile = null;
        audioInput.value = "";
        transcriptInput.value = "";
        selectedBox.hidden = true;
        selectedName.textContent = "";
        status.textContent = "Select an audio recording or transcript to continue.";
        submitButton.disabled = true;
        submitButton.textContent = "Analyze Conversation";
        audioButton.disabled = false;
        transcriptButton.disabled = false;
        cancelButton.disabled = false;
        processing = false;
    }

    function selectFile(file) {
        if (!file) return;

        selectedFile = file;
        selectedName.textContent = file.name;
        selectedBox.hidden = false;
        status.textContent = "Ready to analyze. Check the selected file before continuing.";
        submitButton.disabled = false;
    }

    openButton.addEventListener("click", () => {
        resetModal();
        modal.hidden = false;
        audioButton.focus();
    });

    cancelButton.addEventListener("click", () => {
        if (processing) return;
        modal.hidden = true;
        resetModal();
        openButton.focus();
    });

    modal.addEventListener("click", event => {
        if (event.target === modal && !processing) {
            modal.hidden = true;
            resetModal();
            openButton.focus();
        }
    });

    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && !modal.hidden && !processing) {
            modal.hidden = true;
            resetModal();
            openButton.focus();
        }
    });

    audioButton.addEventListener("click", () => audioInput.click());
    transcriptButton.addEventListener("click", () => transcriptInput.click());

    audioInput.addEventListener("change", () => {
        selectFile(audioInput.files[0]);
    });

    transcriptInput.addEventListener("change", () => {
        selectFile(transcriptInput.files[0]);
    });

    submitButton.addEventListener("click", async () => {
        if (!selectedFile || processing) return;

        processing = true;
        submitButton.disabled = true;
        submitButton.textContent = "Analyzing...";
        audioButton.disabled = true;
        transcriptButton.disabled = true;
        cancelButton.disabled = true;

        status.textContent = selectedFile.name.endsWith(".txt")
            ? "Evaluating transcript and generating compliance results..."
            : "Transcribing audio and running AI quality analysis. This may take a few moments...";

        try {
            await uploadCall(selectedFile);
        } finally {
            modal.hidden = true;
            resetModal();
            openButton.focus();
        }
    });
}

    function init() {
        initNavigation();
        initUserMenu();


        const statusFilter = document.getElementById(
            "filter-status"
        );

        const reviewFilter = document.getElementById(
            "filter-review"
        );

        const refreshButton = document.getElementById(
            "refresh"
        );

        statusFilter.addEventListener("change", event => {

            state.status = event.target.value;

            refresh();
        });

        reviewFilter.addEventListener("change", event => {

            state.reviewOnly = event.target.checked;

            refresh();
        });

        refreshButton.addEventListener(
            "click",
            refresh
        );

        initAnalyzeModal();

        refresh();
    }


    // =====================================================
    // EXPORT HELPERS FOR TESTING
    // =====================================================

    if (
        typeof module !== "undefined" &&
        module.exports
    ) {

        module.exports = {

            splitEvidence,
            findRanges,
            lineSegments,
            collectHighlights,
            straighten

        };

    } else if (document.readyState === "loading") {

        document.addEventListener(
            "DOMContentLoaded",
            init
        );

    } else {

        init();
    }

})();