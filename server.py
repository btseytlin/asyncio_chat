import asyncio
import websockets
import uuid

HOST ='localhost'
PORT = 8765

class ClientAlreadyExistsException(Exception):
    pass

class ClientNotRegisteredInRoomException(Exception):
    pass

class Client():
    def __init__(self, websocket=None,username=None, room=None):
        self.websocket = websocket
        self.username = username
        self.room = None

    @property
    def chat_name(self):
        return self.username

class Room():
    def __init__(self, server=None, loop=None, messages = None, clients = None, uid = None, _name = None):
        self.server = server
        self.loop = loop or asyncio.get_event_loop()
        self.messages = messages or []
        self.clients = clients or set()
        self.uid = uid or str(uuid.uuid4())[:8]
        self._name = _name or None

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, val):
        self._name = val

    def readable_history(self, client):
        history = '\n'.join(['{}: {}'.format(msg[0].chat_name, msg[1]) for msg in self.messages if not msg[2] or client in msg[2]])
        return history

    def is_command(self, message):
        return message[:2] == '::' 

    def get_client(self, websocket):
        for client in self.clients.copy():
            if client.websocket == websocket:

                return client
        return False

    async def on_client_joined(self, client):
        await self.send_message(self, "Welcome to the {}! Here's what happened before you came:".format(self.name), [client], log = False)
        history = self.readable_history(client)
        if history:
            await self.send_text(history, [client])
        await self.send_message(self, '{} connected'.format(client.username))

    async def on_client_disconnected(self, client):
        await self.send_message(self, '{} disconnected'.format(client.username))

    async def handle_command(self, client, message):
        await self.send_message(self, 'Unrecognized command', [client], log = False) 

    async def handle_message(self, client, message):
        if not self.get_client(client.websocket):
            raise(ClientNotRegisteredInRoomException())

        if self.is_command(message):
            await self.handle_command(client, message[2:])
        else:
            await self.send_message(client, message)

    async def register_client(self, websocket, username):
        try:
            client = self.get_client(websocket)
            if not client:
                client = Client(websocket, username)
            self.clients.add(client)
            client.room = self
            await self.on_client_joined(client)
            return client
        except ClientAlreadyExistsException as e:
            await self.server.send('Client already registered', websocket)


    async def remove_client(self, websocket):
        for client in self.clients.copy():
            if client.websocket == websocket:
                self.clients.remove(client)
                await self.on_client_disconnected(client)
                break

    async def send_text(self, message, targets): #Sending text doesn't show an author and is never logged
        if not targets:
            targets = self.clients #If no target is set its a global message

        sending_list = [self.server.send("{}".format(message), client) for client in targets]
        if sending_list:
            done, pending = await asyncio.wait(sending_list)

    async def send_message(self, author, message, targets=[], log = True):
        if not targets:
            targets = self.clients #If no target is set its a global message

        sending_list = [self.server.send("{}: {}".format(author.chat_name, message), client) for client in targets]
        if sending_list:
            done, pending = await asyncio.wait(sending_list)
        if log:
            self.messages.append((author, message, targets))

    @property
    def chat_name(self):
        return "GLOBAL"

class ChatRoom(Room):

    @property
    def chat_name(self):
        return "Chat"


class LobbyRoom(Room):
    async def handle_command(self, client, message):
        command_components = message.split(' ')
        command = command_components[0]
        args = command_components[1:]



        async def handle_join(*args):
            max_args_len = 1
            if len(args) > max_args_len:
                return "Too many arguments, expected {}".format(max_args_len)
            room_name = args[0]

            new_room = None
            for room in self.server.rooms:
                if room.name == room_name:
                    new_room = room
                    break

            if not new_room:
                return "There is no room with name {}.".format(room_name)

            await new_room.register_client(client.websocket, client.username)
            await client.room.remove_client(client.websocket)

            return 0 
            


        async def handle_create(*args):
            max_args_len = 1
            if len(args) > max_args_len:
                return "Too many arguments, expected {}.".format(max_args_len)
            room_name = args[0]

            for room in self.server.rooms:
                if room.name == room_name:
                    return "Room name {} is taken, choose another.".format(room_name)

            new_room = ChatRoom(self.server, self.loop, _name=room_name)
            
            await new_room.register_client(client.websocket, client.username)
            await client.room.remove_client(client.websocket)
            self.server.rooms.append(new_room)
            return 0
        
        available_commands = {
            "join":handle_join,
            "create":handle_create
        }

        if command in available_commands.keys():
            result = await available_commands[command](*args)
            if result:
                await self.send_message(self, 'Error: {}'.format(result), [client], log = False) 
        else:
            await self.send_message(self, 'Unrecognized command', [client], log = False) 

    @property
    def chat_name(self):
        return "Lobby"



class ChatServer:
    def __init__(self, host=HOST, port=PORT, loop=None, messages = None, clients = None, rooms = None):
        self.host = host
        self.port = port
        self.loop = loop or asyncio.get_event_loop()
        self.room = LobbyRoom(self, loop, messages, clients, _name='lobby room')
        self.rooms = rooms or []

    def __str__(self):
        return "ChatServer"

    def get_client(self, websocket):
        client = self.room.get_client(websocket)
        if not client:
            for room in self.rooms:
                client = room.get_client(websocket)
                if client:
                    return client
        else:
            return client
        return None

    async def send(self, message, client):
        if type(client) == Client:
            await client.websocket.send(message)
        else:
            await client.send(message)

    async def handler(self, websocket, path):
        client = None
        while True:
            try:
                client = self.get_client(websocket)
                if not client:
                    await websocket.send('Please register')
                    username = await websocket.recv()
                    client = await self.room.register_client(websocket, username)
                    
                message = await websocket.recv()
                response = await client.room.handle_message(client, message)

            except websockets.exceptions.ConnectionClosed as e:
                if client and client.room:
                    await client.room.remove_client(websocket)                    
                break

    def run(self):
        self.loop.run_until_complete(websockets.serve(self.handler, self.host, self.port))
        self.loop.run_forever()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    chat = ChatServer(loop=loop)
    chat.run()