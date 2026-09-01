import {
  AiOperatorResponseError,
  api,
  parseAiOperatorResponse,
  queryAiOperator,
} from '../src/api/client';

describe('parseAiOperatorResponse', () => {
  it('combines real text events only after a complete response', () => {
    const payload = [
      'data: {"type":"text","content":"Fleet "}',
      '',
      'data: {"type":"action","action":{"command":"restart"}}',
      '',
      'data: {"type":"text","content":"healthy"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n');

    expect(parseAiOperatorResponse(payload)).toBe('Fleet healthy');
  });

  it.each([
    ['backend error', 'data: {"type":"error","message":"provider failed"}\n\ndata: {"type":"done"}\n', 'backend_error'],
    ['missing done', 'data: {"type":"text","content":"partial"}\n', 'incomplete_response'],
    ['malformed event', 'data: not-json\n\ndata: {"type":"done"}\n', 'invalid_response'],
    ['unknown event', 'data: {"type":"promise","content":"fake"}\n\ndata: {"type":"done"}\n', 'invalid_response'],
    ['event after done', 'data: {"type":"done"}\n\ndata: {"type":"text","content":"late"}\n', 'invalid_response'],
    ['empty response', 'data: {"type":"done"}\n', 'invalid_response'],
  ])('rejects %s without inventing an answer', (_name, payload, code) => {
    expect(() => parseAiOperatorResponse(payload)).toThrow(AiOperatorResponseError);
    try {
      parseAiOperatorResponse(payload);
    } catch (error) {
      expect((error as AiOperatorResponseError).code).toBe(code);
    }
  });
});

describe('queryAiOperator', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('uses the authenticated backend route and its query contract', async () => {
    const post = jest.spyOn(api, 'post').mockResolvedValue({
      data: 'data: {"type":"text","content":"Observed"}\n\ndata: {"type":"done"}\n',
    });

    await expect(queryAiOperator('  fleet status?  ')).resolves.toBe('Observed');
    expect(post).toHaveBeenCalledWith(
      '/ai/query',
      { query: 'fleet status?' },
      {
        headers: { Accept: 'text/event-stream' },
        responseType: 'text',
        timeout: 35_000,
      }
    );
  });

  it('rejects an empty query before making a request', async () => {
    const post = jest.spyOn(api, 'post');

    await expect(queryAiOperator('   ')).rejects.toMatchObject({ code: 'invalid_response' });
    expect(post).not.toHaveBeenCalled();
  });
});
