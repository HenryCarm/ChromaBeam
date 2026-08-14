const vm = require('vm');

function pyMulberry(seed) {
    let state = seed >>> 0;
    return function() {
        state = (state + 0x6D2B79F5) >>> 0;
        let t = state;
        t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
        // Python: t ^= ((t + ((t ^ (t >> 7)) * (t | 61))) & 0xFFFFFFFF)
        t ^= (t + Math.imul(t ^ (t >>> 7), t | 61)) >>> 0;
        t = (t ^ (t >>> 14)) >>> 0;
        return t;
    };
}

function jsMulberryCurrent(seed) {
    let state = seed >>> 0;
    return function() {
        state = (state + 0x6D2B79F5) >>> 0;
        let t = state;
        t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
        // Current JS web/fountain.js:
        t ^= (t + Math.imul(t ^ (t >>> 7), 61)) >>> 0;
        t = (t ^ (t >>> 14)) >>> 0;
        return t;
    };
}

console.log("Testing seed 1337:");
const py = pyMulberry(1337);
const jsCurr = jsMulberryCurrent(1337);

console.log("Python match version:", py(), py(), py());
console.log("Current JS in repo:  ", jsCurr(), jsCurr(), jsCurr());
