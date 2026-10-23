import { StrictMode, useEffect, useState, type PropsWithChildren } from 'react';
import { TextInput } from 'react-native';
import { act, cleanup, fireEvent, render, renderHook } from '@testing-library/react-native';
import { type QueryClient, useQueryClient } from '@tanstack/react-query';
import { SessionBoundary } from '../src/components/SessionBoundary';
import { useSessionScope } from '../src/hooks/useSessionScope';
import { useAppStore } from '../src/store';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

const fixtureClients = new Set<QueryClient>();
const detachedEntries = new Set<{ destroy: () => void }>();

function PrivateView({ observe }: { observe: (client: QueryClient) => void }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState('');
  useEffect(() => {
    fixtureClients.add(client);
    observe(client);
  }, [client, observe]);
  return <TextInput testID="private-draft" value={draft} onChangeText={setDraft} />;
}

// Match App's real revision key without loading native navigation or screens.
function SessionHarness({ observe }: { observe: (client: QueryClient) => void }) {
  const revision = useAppStore((state) => state.authRevision);
  return <SessionBoundary key={revision}><PrivateView observe={observe} /></SessionBoundary>;
}

beforeEach(() => {
  jest.clearAllMocks();
  useAppStore.setState(useAppStore.getInitialState(), true);
  useAppStore.getState().setToken('fixture-session-a');
});

afterEach(async () => {
  await cleanup();
  // A deliberate late write to detached A remains isolated from B, but the
  // test still owns that old client and must release its GC timer.
  for (const client of fixtureClients) client.clear();
  // Query.fetch's finally can reschedule GC after removal, and MutationCache
  // clear removes entries without destroying their timers. We own both here.
  for (const entry of detachedEntries) entry.destroy();
  fixtureClients.clear();
  detachedEntries.clear();
  jest.restoreAllMocks();
});

describe('real query cache and keyed private subtree', () => {
  it('clears A synchronously and gives B an independent cache and empty local UI', async () => {
    const clients: QueryClient[] = [];
    const observe = (client: QueryClient) => { clients.push(client); };
    const screen = await render(<SessionHarness observe={observe} />);
    const clientA = clients[0];
    clientA.setQueryData(['private'], { owner: 'A' });
    const mutationA = clientA.getMutationCache().build(clientA, { mutationKey: ['private-a'] });
    detachedEntries.add(mutationA);
    await fireEvent.changeText(screen.getByTestId('private-draft'), 'Private draft A');
    expect(screen.getByTestId('private-draft').props.value).toBe('Private draft A');

    await act(() => {
      useAppStore.getState().setToken('fixture-session-b');
      // These assertions run before the keyed React cleanup can be awaited.
      expect(clientA.getQueryData(['private'])).toBeUndefined();
      expect(clientA.getMutationCache().getAll()).toEqual([]);
    });

    const clientB = clients[clients.length - 1];
    expect(clientB).not.toBe(clientA);
    expect(clientB.getQueryData(['private'])).toBeUndefined();
    expect(screen.getByTestId('private-draft').props.value).toBe('');
    clientB.setQueryData(['private'], { owner: 'B' });
    clientA.setQueryData(['private'], { owner: 'late A' });
    expect(clientB.getQueryData(['private'])).toEqual({ owner: 'B' });
  });

  it('does not wait for asynchronous cancellation before clearing private data', async () => {
    const cancellation = deferred<void>();
    const clients: QueryClient[] = [];
    await render(<SessionHarness observe={(client) => { clients.push(client); }} />);
    const clientA = clients[0];
    clientA.setQueryData(['private'], { owner: 'A' });
    const cancel = jest.spyOn(clientA, 'cancelQueries').mockReturnValue(cancellation.promise);
    await act(() => {
      useAppStore.getState().setToken('fixture-session-b');
      expect(cancel).toHaveBeenCalled();
      expect(clientA.getQueryData(['private'])).toBeUndefined();
    });
    expect(clients[clients.length - 1]).not.toBe(clientA);
    cancellation.resolve();
    await cancellation.promise;
  });

  it('does not place a late A query result into the B cache', async () => {
    const response = deferred<{ owner: string }>();
    const clients: QueryClient[] = [];
    await render(<SessionHarness observe={(client) => { clients.push(client); }} />);
    const clientA = clients[0];
    const request = clientA.fetchQuery({
      queryKey: ['pending-private'], queryFn: () => response.promise, retry: false,
    });
    const pendingQuery = clientA.getQueryCache().find({ queryKey: ['pending-private'] });
    if (pendingQuery) detachedEntries.add(pendingQuery);
    const outcome = request.catch(() => undefined);
    await act(() => {
      useAppStore.getState().setToken('fixture-session-b');
      expect(clientA.getQueryCache().getAll()).toEqual([]);
    });
    const clientB = clients[clients.length - 1];
    response.resolve({ owner: 'A' });
    await outcome;
    expect(clientB.getQueryData(['pending-private'])).toBeUndefined();
    expect(clientA.getQueryData(['pending-private'])).toBeUndefined();
  });

  it('clears its cache on unmount even without an account transition', async () => {
    const clients: QueryClient[] = [];
    const screen = await render(<SessionHarness observe={(client) => { clients.push(client); }} />);
    const client = clients[0];
    client.setQueryData(['private'], { owner: 'A' });
    await screen.unmount();
    expect(client.getQueryCache().getAll()).toEqual([]);
  });
});

describe('session scope origin and liveness', () => {
  it('invalidates callbacks after unmount while the same token remains current', async () => {
    const { result, unmount } = await renderHook(() => useSessionScope());
    const scopeA = result.current;
    const callbackA = () => scopeA.isActive();
    expect(callbackA()).toBe(true);
    await unmount();
    expect(useAppStore.getState().auth.token).toBe('fixture-session-a');
    expect(callbackA()).toBe(false);
  });

  it('rejects an old render scope before React cleanup and never reactivates it on ABA', async () => {
    const { result } = await renderHook(() => useSessionScope());
    const scopeA = result.current;
    await act(() => {
      useAppStore.getState().setToken('fixture-session-b');
      expect(scopeA.isActive()).toBe(false);
    });
    const scopeB = result.current;
    expect(scopeB.isActive()).toBe(true);
    await act(() => {
      useAppStore.getState().logout();
      useAppStore.getState().setToken('fixture-session-a');
      expect(scopeA.isActive()).toBe(false);
      expect(scopeB.isActive()).toBe(false);
    });
    expect(result.current.isActive()).toBe(true);
    expect(result.current.lease.revision).toBeGreaterThan(scopeA.lease.revision);
    expect(Object.isFrozen(scopeA.lease)).toBe(true);
  });

  it('keeps the committed scope active in StrictMode and inactive after unmount', async () => {
    const wrapper = ({ children }: PropsWithChildren) => <StrictMode>{children}</StrictMode>;
    const { result, unmount } = await renderHook(() => useSessionScope(), { wrapper });
    const scope = result.current;
    expect(scope.isActive()).toBe(true);
    await unmount();
    expect(scope.isActive()).toBe(false);
  });
});
