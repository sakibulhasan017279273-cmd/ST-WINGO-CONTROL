const PASSWORD = "12345";

const API_URL =
    "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json";

const ROUND_SECONDS = 60;

let latestIssue = null;
let currentSignal = null;
let currentNumbers = [];
let history = [];

try {
    history = JSON.parse(
        localStorage.getItem("st_wingo_history") || "[]"
    );
} catch {
    history = [];
}


/* ================================
   BASIC HELPERS
================================ */

const $ = id => document.getElementById(id);

function saveHistory() {
    localStorage.setItem(
        "st_wingo_history",
        JSON.stringify(history.slice(0, 60))
    );
}

function bigSmall(number) {
    return Number(number) >= 5
        ? "BIG"
        : "SMALL";
}

function nextPeriod(issue) {
    try {
        return String(BigInt(issue) + 1n);
    } catch {
        return String(Number(issue) + 1);
    }
}


/* ================================
   SIGNAL ENGINE
================================ */

function generateSignal(list) {

    const numbers = list
        .slice(0, 20)
        .map(item => Number(item.number))
        .filter(Number.isFinite);

    if (!numbers.length) {
        return {
            signal: "WAIT",
            numbers: []
        };
    }

    const sides = numbers.map(bigSmall);

    let big = 0;
    let small = 0;


    /* Recent trend */

    sides.slice(0, 6).forEach((side, index) => {

        const weight = 6 - index;

        if (side === "BIG") {
            big += weight;
        } else {
            small += weight;
        }
    });


    /* Reversal after strong streak */

    if (
        sides[0] === sides[1] &&
        sides[1] === sides[2]
    ) {

        if (sides[0] === "BIG") {
            small += 8;
        } else {
            big += 8;
        }
    }


    /* Alternating sequence */

    if (
        sides.length >= 4 &&
        sides[0] !== sides[1] &&
        sides[1] !== sides[2] &&
        sides[2] !== sides[3]
    ) {

        if (sides[0] === "BIG") {
            small += 5;
        } else {
            big += 5;
        }
    }


    /* Frequency */

    const bigCount =
        sides.filter(x => x === "BIG").length;

    const smallCount =
        sides.filter(x => x === "SMALL").length;

    if (bigCount < smallCount) {
        big += 3;
    }

    if (smallCount < bigCount) {
        small += 3;
    }


    const prediction =
        big >= small
            ? "BIG"
            : "SMALL";


    /* Number selection */

    const pool =
        prediction === "BIG"
            ? [5, 6, 7, 8, 9]
            : [0, 1, 2, 3, 4];

    const frequency = {};

    pool.forEach(n => {
        frequency[n] = 0;
    });

    numbers.forEach(n => {
        if (pool.includes(n)) {
            frequency[n]++;
        }
    });

    pool.sort(
        (a, b) =>
            frequency[b] - frequency[a]
    );

    const selectedNumbers = [
        pool[0],
        pool[1]
    ];


    const total = big + small;

    const confidence =
        total > 0
            ? Math.min(
                98,
                Math.round(
                    60 +
                    (
                        Math.max(big, small) /
                        total
                    ) * 30
                )
            )
            : 60;


    return {
        signal: prediction,
        numbers: selectedNumbers,
        confidence
    };
}


/* ================================
   API
================================ */

async function getWinGoData() {

    const response = await fetch(
        API_URL +
        "?ts=" +
        Date.now(),
        {
            method: "GET",
            cache: "no-store"
        }
    );

    if (!response.ok) {
        throw new Error(
            "API Error: " +
            response.status
        );
    }

    const json =
        await response.json();

    const list =
        json?.data?.list;

    if (
        !Array.isArray(list) ||
        !list.length
    ) {
        throw new Error(
            "Invalid API response"
        );
    }

    return list;
}


/* ================================
   RESULT TRACKING
================================ */

function checkPreviousResult(
    issue,
    actualNumber
) {

    if (
        !currentSignal ||
        !latestIssue ||
        issue === latestIssue
    ) {
        return;
    }

    const actual =
        bigSmall(actualNumber);

    let result;

    if (
        currentNumbers.includes(
            Number(actualNumber)
        )
    ) {
        result = "JACKPOT";
    } else if (
        currentSignal === actual
    ) {
        result = "WIN";
    } else {
        result = "LOSS";
    }

    history.unshift({
        period: issue,
        signal: currentSignal,
        number: Number(actualNumber),
        selected:
            [...currentNumbers],
        result,
        time: Date.now()
    });

    history =
        history.slice(0, 60);

    saveHistory();

    showResult(
        result,
        actualNumber
    );

    renderHistory();
}


/* ================================
   SIGNAL UPDATE
================================ */

async function updateSignal() {

    try {

        const list =
            await getWinGoData();

        const latest =
            list[0];

        const issue =
            String(
                latest.issueNumber
            );

        const actual =
            Number(
                latest.number
            );


        checkPreviousResult(
            issue,
            actual
        );


        const prediction =
            generateSignal(list);


        currentSignal =
            prediction.signal;

        currentNumbers =
            prediction.numbers;

        latestIssue =
            issue;


        const period =
            nextPeriod(issue);


        if ($("period")) {
            $("period").textContent =
                period;
        }

        if ($("signal")) {

            $("signal").textContent =
                currentSignal;

            $("signal").className =
                "signal " +
                (
                    currentSignal === "BIG"
                        ? "big"
                        : "small"
                );
        }

        if ($("number")) {

            $("number").textContent =
                currentNumbers.join(
                    " / "
                );
        }

        if ($("round-status")) {

            $("round-status").textContent =
                prediction.confidence +
                "% CONFIDENCE";
        }

        if ($("connection-status")) {

            $("connection-status")
                .textContent =
                "LIVE";

            $("connection-status")
                .classList.add(
                    "online"
                );
        }

    } catch (error) {

        console.error(
            "WinGo API:",
            error
        );

        if ($("connection-status")) {

            $("connection-status")
                .textContent =
                "API ERROR";
        }
    }
}


/* ================================
   COUNTDOWN
================================ */

function updateCountdown() {

    const now =
        Math.floor(
            Date.now() / 1000
        );

    let remaining =
        ROUND_SECONDS -
        (
            now %
            ROUND_SECONDS
        );

    if (remaining === 0) {
        remaining =
            ROUND_SECONDS;
    }

    if ($("countdown")) {

        $("countdown").textContent =
            String(
                remaining
            ).padStart(
                2,
                "0"
            );

        $("countdown")
            .classList.toggle(
                "danger",
                remaining <= 5
            );
    }
}


/* ================================
   RESULT DISPLAY
================================ */

function showResult(
    result,
    number
) {

    const box =
        $("result-box");

    const resultEl =
        $("result");

    const text =
        $("result-text");

    if (!box || !resultEl) {
        return;
    }

    box.classList.remove(
        "hidden"
    );

    resultEl.className =
        "result " +
        result.toLowerCase();

    resultEl.textContent =
        result;

    if (text) {

        text.textContent =
            "RESULT NUMBER: " +
            number;
    }

    setTimeout(
        () => {
            box.classList.add(
                "hidden"
            );
        },
        3500
    );
}


/* ================================
   HISTORY UI
================================ */

function renderHistory() {

    const box =
        $("history");

    if (!box) {
        return;
    }

    if (!history.length) {

        box.innerHTML =
            '<div class="empty">No results yet</div>';

        return;
    }

    box.innerHTML =
        history
            .slice(0, 20)
            .map(item => {

                const resultClass =
                    String(
                        item.result
                    ).toLowerCase();

                return `
                    <div class="history-item">

                        <span class="history-period">
                            ${item.period}
                        </span>

                        <span class="history-signal">
                            ${item.signal}
                        </span>

                        <span class="history-result ${resultClass}">
                            ${item.result}
                        </span>

                    </div>
                `;
            })
            .join("");
}


/* ================================
   ACCESS
================================ */

function unlock() {

    const input =
        $("password");

    if (!input) {
        return;
    }

    if (
        input.value ===
        PASSWORD
    ) {

        if ($("password-error")) {
            $("password-error")
                .textContent = "";
        }

        $("access-card")
            ?.classList.add(
                "hidden"
            );

        $("control-card")
            ?.classList.remove(
                "hidden"
            );

        $("actions")
            ?.classList.remove(
                "hidden"
            );

        updateSignal();

    } else {

        if ($("password-error")) {

            $("password-error")
                .textContent =
                "Incorrect password";
        }

        input.value = "";
        input.focus();
    }
}


/* ================================
   BUTTONS
================================ */

$("access-btn")
    ?.addEventListener(
        "click",
        unlock
    );

$("password")
    ?.addEventListener(
        "keydown",
        event => {

            if (
                event.key === "Enter"
            ) {
                unlock();
            }
        }
    );

$("hide-btn")
    ?.addEventListener(
        "click",
        () => {

            $("control-card")
                ?.classList.add(
                    "hidden"
                );
        }
    );

$("show-btn")
    ?.addEventListener(
        "click",
        () => {

            $("control-card")
                ?.classList.remove(
                    "hidden"
                );
        }
    );


/* ================================
   START
================================ */

renderHistory();

updateCountdown();

setInterval(
    updateCountdown,
    250
);

setInterval(
    updateSignal,
    4000
);
