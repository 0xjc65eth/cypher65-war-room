import React, { useState, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native';
import { useSnapshot } from '../../hooks/useSnapshot';
import { api } from '../../api/client';

interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  text: string;
  ts: number;
}

/**
 * AI Operator screen.
 *
 * In production this screen sends user messages to the backend endpoint
 * `POST /api/ai/chat`. If the backend endpoint is not yet deployed or returns
 * an error, the screen falls back to a local simulated response so the UI
 * remains usable. Remove the fallback once the AI backend is live.
 */
export const AiOperatorScreen = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const { snapshot } = useSnapshot();
  const listRef = useRef<FlatList<ChatMessage>>(null);

  const appendMessage = (message: ChatMessage) => {
    setMessages((prev) => [...prev, message]);
  };

  const generateFallbackResponse = (): string => {
    const fleetSummary = (snapshot?.axe_fleet as any[])?.length ?? 0;
    if (fleetSummary > 0) {
      return `I see ${fleetSummary} device(s) connected. How can I help you with your fleet?`;
    }
    return "I'm connected to your operation. Ask me about fleet status, block probabilities, or market opportunities.";
  };

  const sendMessage = async () => {
    if (!input.trim() || sending) return;

    const userMessage: ChatMessage = {
      id: `${Date.now()}_u`,
      role: 'user',
      text: input.trim(),
      ts: Date.now(),
    };

    appendMessage(userMessage);
    setInput('');
    setSending(true);

    try {
      const { data } = await api.post('/ai/chat', {
        message: userMessage.text,
        context: { fleet: snapshot },
      });

      const aiResponse: ChatMessage = {
        id: `${Date.now()}_a`,
        role: 'ai',
        text: data?.response || data?.text || generateFallbackResponse(),
        ts: Date.now(),
      };
      appendMessage(aiResponse);
    } catch (error) {
      // Fallback simulated response while the AI backend is not available.
      const fallback: ChatMessage = {
        id: `${Date.now()}_a`,
        role: 'ai',
        text: `[SIMULATED] ${generateFallbackResponse()}`,
        ts: Date.now(),
      };
      appendMessage(fallback);
    } finally {
      setSending(false);
      listRef.current?.scrollToEnd({ animated: true });
    }
  };

  const renderItem = ({ item }: { item: ChatMessage }) => (
    <View
      style={[
        styles.bubble,
        item.role === 'user' ? styles.userBubble : styles.aiBubble,
      ]}
    >
      <Text style={item.role === 'user' ? styles.userText : styles.aiText}>{item.text}</Text>
    </View>
  );

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      keyboardVerticalOffset={90}
    >
      <FlatList
        ref={listRef}
        style={styles.list}
        data={messages}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={
          <Text style={styles.hint}>
            Ask the CYPHER65 AI Operator anything about your fleet, block probability, or market.
          </Text>
        }
      />
      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          placeholder="Type a command..."
          placeholderTextColor="#64748b"
          value={input}
          onChangeText={setInput}
          onSubmitEditing={sendMessage}
          editable={!sending}
        />
        <TouchableOpacity style={styles.sendButton} onPress={sendMessage} disabled={sending}>
          {sending ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.sendText}>Send</Text>}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0b0f19',
  },
  list: {
    flex: 1,
    padding: 16,
  },
  listContent: {
    paddingBottom: 8,
  },
  bubble: {
    borderRadius: 12,
    padding: 12,
    marginVertical: 4,
    maxWidth: '80%',
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#0ea5e9',
  },
  aiBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#1f2937',
  },
  userText: {
    color: '#ffffff',
  },
  aiText: {
    color: '#e2e8f0',
  },
  hint: {
    color: '#64748b',
    textAlign: 'center',
    marginTop: 24,
    fontStyle: 'italic',
  },
  inputRow: {
    flexDirection: 'row',
    padding: 12,
    backgroundColor: '#111827',
    alignItems: 'center',
  },
  input: {
    flex: 1,
    backgroundColor: '#1f2937',
    color: '#f8fafc',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginRight: 8,
  },
  sendButton: {
    backgroundColor: '#0ea5e9',
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  sendText: {
    color: '#ffffff',
    fontWeight: '600',
  },
});
