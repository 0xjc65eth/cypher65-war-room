import { act, cleanup, fireEvent, render } from '@testing-library/react-native';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { api } from '../src/api/client';
import { SessionBoundary } from '../src/components/SessionBoundary';
import { AiOperatorScreen } from '../src/screens/AI/AiOperatorScreen';
import { useAppStore } from '../src/store';

// Exercise the real screen, axios serialization and synchronous bearer fence.
// Only the transport adapter is synthetic; no provider or native push is used.
const originalAdapter = api.defaults.adapter;
const privateQuestionA = 'Fixture account A: private device-a maintenance budget 42';
const sent: { url: string | undefined; bearer: unknown; body: unknown }[] = [];
const finish: (() => void)[] = [];
const pending = new Set<Promise<unknown>>();

function ScreenHarness() {
  const revision = useAppStore((state) => state.authRevision);
  return <SessionBoundary key={revision}><AiOperatorScreen /></SessionBoundary>;
}

async function finishAfterUnmount() {
  // Avoid measuring FlatList scrolling/render timing: this suite tests outgoing
  // native-event authority, and completes replies only after the view unmounts.
  await cleanup();
  await act(async () => {
    for (const resolve of finish) resolve();
    await Promise.allSettled([...pending]);
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  sent.length = 0;
  finish.length = 0;
  pending.clear();
  useAppStore.setState(useAppStore.getInitialState(), true);
  useAppStore.getState().setToken('fixture-session-a');
  api.defaults.adapter = (config: InternalAxiosRequestConfig) => {
    sent.push({
      url: config.url, bearer: config.headers.get('Authorization'),
      body: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
    });
    return new Promise<AxiosResponse>((resolve) => {
      finish.push(() => resolve({
        config, status: 200, statusText: 'fixture', headers: {},
        data: 'data: {"type":"text","content":"Fixture answer"}\n\ndata: {"type":"done"}\n\n',
      }));
    });
  };
});

afterEach(async () => {
  await finishAfterUnmount();
  api.defaults.adapter = originalAdapter;
  jest.restoreAllMocks();
});

describe('screen-native event session authority', () => {
  it('does not send A private text under B from a retained native submit handler before cleanup', async () => {
    const screen = await render(<ScreenHarness />);
    await fireEvent.changeText(screen.getByLabelText('Question for AI Operator'), privateQuestionA);
    // The screen binds this same sendMessage function to submit and press.
    // Retain the native TextInput handler directly, without renderer internals.
    const nativeHandler: unknown = screen.getByLabelText('Question for AI Operator').props.onSubmitEditing;
    if (typeof nativeHandler !== 'function') throw new Error('Fixture native handler is missing');
    let sentBeforeCleanup: typeof sent = [];
    await act(() => {
      useAppStore.getState().setToken('fixture-session-b');
      pending.add(nativeHandler());
      // Capture in the same synchronous turn as the transition and dispatch.
      sentBeforeCleanup = [...sent];
    });
    await finishAfterUnmount();
    expect(sentBeforeCleanup).toEqual([]);
    expect(sent).toEqual([]);
  });

  it('does not send from an earlier A render after logout and same-token restoration', async () => {
    const screen = await render(<ScreenHarness />);
    await fireEvent.changeText(screen.getByLabelText('Question for AI Operator'), privateQuestionA);
    const submit: unknown = screen.getByLabelText('Question for AI Operator').props.onSubmitEditing;
    if (typeof submit !== 'function') throw new Error('Fixture submit handler is missing');
    await act(() => {
      useAppStore.getState().logout();
      useAppStore.getState().setToken('fixture-session-a');
      pending.add(submit());
    });
    await finishAfterUnmount();
    expect(sent).toEqual([]);
  });

  it('does not send from an unmounted A view while its token remains current', async () => {
    const screen = await render(<ScreenHarness />);
    await fireEvent.changeText(screen.getByLabelText('Question for AI Operator'), privateQuestionA);
    const submit: unknown = screen.getByLabelText('Question for AI Operator').props.onSubmitEditing;
    if (typeof submit !== 'function') throw new Error('Fixture submit handler is missing');
    await screen.unmount();
    await act(() => { pending.add(submit()); });
    await finishAfterUnmount();
    expect(sent).toEqual([]);
  });

  it('preserves current-owner submission with real axios body and bearer binding', async () => {
    const screen = await render(<ScreenHarness />);
    await fireEvent.changeText(screen.getByLabelText('Question for AI Operator'), privateQuestionA);
    const submit: unknown = screen.getByLabelText('Question for AI Operator').props.onSubmitEditing;
    if (typeof submit !== 'function') throw new Error('Fixture submit handler is missing');
    await act(() => { pending.add(submit()); });
    expect(sent).toEqual([{
      url: '/ai/query', bearer: 'Bearer fixture-session-a', body: { query: privateQuestionA },
    }]);
    await finishAfterUnmount();
  });
});
