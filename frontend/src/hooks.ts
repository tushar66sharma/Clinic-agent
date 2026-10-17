import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

/** Load data from the API with loading, error and reload handling. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      setData(await loadRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unexpected error.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "access_token_required") return "This action needs the access token. Add it on the System page.";
    return e.message;
  }
  return "Unexpected error.";
}
