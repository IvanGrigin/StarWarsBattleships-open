/* tslint:disable */
/* eslint-disable */

/**
 * Result is ALWAYS a JSON object string: {"ok":true,"events":[...],"state":{...}}
 * or {"ok":false,"error":"code","detail":"..."}. Illegal commands never throw —
 * the frontend must read the `ok` field.
 */
export function apply_command(state_json: string, cmd_json: string): string;

export function create_match(seed: number, round_limit: number): string;

export function is_terminal(state_json: string): boolean;

export function legal_actions(state_json: string): string;

export function ruleset_hash(): string;

export function state_hash(state_json: string): string;

export function version(): string;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly apply_command: (a: number, b: number, c: number, d: number) => [number, number, number, number];
    readonly create_match: (a: number, b: number) => [number, number, number, number];
    readonly is_terminal: (a: number, b: number) => [number, number, number];
    readonly legal_actions: (a: number, b: number) => [number, number, number, number];
    readonly ruleset_hash: () => [number, number];
    readonly state_hash: (a: number, b: number) => [number, number, number, number];
    readonly version: () => [number, number];
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
