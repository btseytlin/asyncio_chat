import asyncio
import websockets

#Step 1: make a minimal asyncio ws chat

HOST ='localhost'
PORT = 8765

class ChatBackEnd:
    def __init__(self, host=HOST, port=PORT, loop=None, messages = [], clients = set()):
        self.host = host
        self.port = port
        self.loop = loop or asyncio.get_event_loop()
        self.clients = clients
        self.messages = messages

    async def process_message(self, author, message, sender = None):
        
        if author is self:
            author = 'SYSTEM'
        print(author, message)
        self.messages.append((author, message))
        #send message to all clients
        
        sync_list = [client.send("{}: {}".format(author, message)) for client in self.clients if client != sender]
        if sync_list:
            done, pending = await asyncio.wait(sync_list)

    async def handler(self, websocket, path):
        while True:
            if not websocket in self.clients:
                self.clients.add(websocket)
                history = '\n'.join(['{}: {}'.format(msg[0], msg[1]) for msg in self.messages])
                await websocket.send(history)
                await self.process_message(self, '{} connected'.format(str(id(websocket))))
            try:
                message = await websocket.recv()
                await self.process_message(id(websocket), message, websocket)

            except websockets.exceptions.ConnectionClosed as e:
                self.clients.remove(websocket)
                await self.process_message(self, '{} disconnected'.format(str(id(websocket))))
                break

    def run(self):
        self.messages.append(('SYSTEM','Server started up'))
        self.loop.run_until_complete(websockets.serve(self.handler, self.host, self.port))
        self.loop.run_forever()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    chat = ChatBackEnd(loop=loop)
    chat.run()

